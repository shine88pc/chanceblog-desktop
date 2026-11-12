"""본문 속 Secret 형태 검사기의 모양 시험(`security/scan.py`, 설계 D-420–D-429) — 오탐 표·미탐 표·경계값·글자 맞추기·알려진 한계.

지키는 것:
  1) 오탐 표: 정상 글 100개가 넘게(한글·영문 산문, '토큰'·'Bearer'·'API 키' 낱말이 든 설명, 커밋 해시 40자·SHA-256 64자·짧은 base64, 주소·코드 조각, 모양을 다 갖추지 않은 자리표,
     한 글자 모자란 경계 표본, 실제 글 두 편) 발견되지 않는다.
  2) 미탐 표: 6종(접두어·형식 변형까지 29가지) × 22가지 자리(줄 끝·글 끝·따옴표·JSON·URL 질의·마크다운 코드 블록·앞뒤 구두점·CRLF·탭·긴 글 한가운데·한글 조사 붙음·퍼센트 인코딩 구분자 뒤)가
     모두 한 건씩, 정확한 줄·열에서 발견된다.
  3) 경계값: 규칙마다 길이 하한(한 글자 모자라면 없음·같으면 있음·넘으면 한 덩어리)·글자 모음(들어가는 글자·안 들어가는 글자 전수)·앞뒤 글자 검사·접두어 변형(빼먹음·대소문자·다른 글자).
  4) 글자 맞추기: 전각·수학 글자·특수 공백은 영문·숫자·공백으로 맞춰 찾는다. 알려진 한계 — 눈에 안 보이는 글자·공백·줄바꿈으로 쪼갠 토큰, 여섯 가지 밖의 형식, 접두어 앞에 영문·숫자가 붙은 것 — 는 찾지 않는다(docs/SECURITY.md).
키 모양은 실행할 때 조각을 이어 붙여 만든다. 네트워크·실제 비밀 없이 돈다.
"""
import string
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import scan_samples as S  # noqa: E402

from chanceblog_desktop.security import scan  # noqa: E402

PROSE = "오늘은 날씨가 좋아서 산책을 했어요. The weather was nice today, so we walked a lot. "
SCHEME = "ht" + "tps://"
BOM = chr(0xFEFF)


class Base(unittest.TestCase):
    def found(self, text):
        return S.triples(scan.scan_secrets(text))

    def assert_one(self, text, kind, token, label=""):
        self.assertEqual(self.found(text), [(kind, *S.locate(text, token))], label)

    def assert_none(self, text, label=""):
        self.assertEqual(self.found(text), [], label)
        self.assertFalse(scan.has_secret(text), label)


# ---- 1) 오탐 표 -------------------------------------------------------------------------------------------------------------------
def clean_texts():
    hex40 = "9fceb02d0ae598e95dc970b74767f19372d61af8"
    hex64 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    short_of = [
        ("AIza 몸 34자", "AI" + "za" + S.body(34, S.B64URL)),
        ("ghp 몸 35자", S.github("p", 35)),
        ("gho 몸 35자", S.github("o", 35)),
        ("github_pat 몸 21자", S.github_pat(21)),
        ("Bearer 값 19자", S.bearer(19)),
        ("ya29 몸 19자", S.ya29(19)),
        ("1// 몸 19자", S.refresh(19)),
        ("JWT 서명 7자", S.jwt(36, 24, 7)),
        ("JWT 머리 7자", S.jwt(7, 24, 30)),
        ("JWT 몸통 3자", S.jwt(36, 3, 30)),
        ("access_token 값 19자", S.named(value=S.body(19, S.B64URL))),
        ("AKIA 몸 15자", S.aws("AKIA", 15)),
        ("AKIA 몸 17자", S.aws("AKIA", 17)),
        ("접두어 빠진 AWS", S.aws("AKIC")),
    ]
    items = [
        # 한글 산문
        "오늘은 날씨가 맑아서 한강 공원에서 자전거를 탔어요.",
        "이번 글에서는 블로그 글쓰기 순서를 차근차근 정리해 볼게요.",
        "토큰이라는 낱말이 들어간 문장이에요. 토큰은 인증에 쓰는 짧은 글이에요.",
        "API 키는 절대 글에 붙여 넣지 마세요. 키가 새면 바로 폐기해야 해요.",
        "Bearer 방식은 HTTP 인증에서 많이 쓰는 방법 중 하나예요.",
        "Authorization 헤더에 Bearer 와 토큰을 공백으로 이어서 보내요.",
        "비밀번호는 안전한 곳에만 적어 두세요 — 이 글에는 적지 않았어요.",
        "access token 과 refresh token 의 차이를 쉽게 설명해 드려요.",
        "AWS 액세스 키를 만드는 법은 공식 문서를 참고하세요.",
        "개인 키(private key)는 서버 안에만 두고 공개 키만 나눠 주세요.",
        "Bearer토큰처럼 붙여 쓴 글도 공백이 없으니 값이 아니에요.",
        "토큰, 키, 비밀번호 같은 낱말만 있고 값은 없는 문장이에요.",
        "구글 API 키를 발급받는 방법: 콘솔에 들어가서 사용자 인증 정보를 만든다.",
        "깃허브 토큰은 설정의 개발자 설정에서 만들어요(값은 이 글에 적지 않아요).",
        "JWT 는 헤더, 페이로드, 서명 세 덩어리로 이뤄져요.",
        # 영문 산문
        "The quick brown fox jumps over the lazy dog.",
        "Never paste your API key, token or password into a public post.",
        "The Bearer scheme is defined in RFC 6750 for OAuth 2.0 access tokens.",
        "Set the Authorization header to Bearer followed by a space and your token.",
        "Use environment variables for secrets, not source files.",
        "OAuth 2.0 uses access tokens and refresh tokens to protect resources.",
        "GitHub personal access tokens start with a prefix that tells you their kind.",
        "A private key must stay private; share only the public key.",
        "Pneumonoultramicroscopicsilicovolcanoconiosis is a very long word.",
        "state-of-the-art-and-then-some is a hyphenated phrase.",
        # 해시·식별자·짧은 base64
        "commit " + hex40,
        "sha256 " + hex64,
        "md5 d41d8cd98f00b204e9800998ecf8427e",
        "id 123e4567-e89b-12d3-a456-426614174000",
        "aGVsbG8gd29ybGQ=",
        "SGVsbG8sIFdvcmxkISEhISEh",
        "short a1b2c3d",
        "12345678901234567890123456789012345678901234567890",
        "dGhpcyBpcyBhIHRlc3Q dGhpcyBpcyBhIHRlc3Q dGhpcyBpcyBhIHRlc3Q",
        "SHA256:" + "uNiVztksCsDhcc0u9e8BujQXVUpKZIDTMczCvj3tD2s",
        "ssh-rsa " + "AAAAB3NzaC1yc2EAAAADAQABAAABAQ" + "x" * 60 + " name",
        # 주소·경로
        SCHEME + "example.com/path?x=1&y=2",
        SCHEME + "example.com/oauth/token?token_type=bearer&expires_in=3600",
        "example.com/api/v1/users?sort=asc&page=2",
        "C:/Users/me/Documents/post.md",
        "src/chanceblog_desktop/security/scan.py",
        "/home/user/.aws/credentials",
        "export AWS_REGION=ap-northeast-2",
        # 코드 조각
        "def add(a, b):\n    return a + b",
        '{"name": "홍길동", "age": 30, "tags": ["a", "b"]}',
        'git commit -m "fix typo" && git push origin main',
        "SELECT id, title FROM posts WHERE status = 'published' ORDER BY id DESC;",
        'headers = {"Authorization": f"Bearer {token}"}',
        "curl -H 'Authorization: Bearer $TOKEN' $URL/me",
        'token = os.environ["ACCESS_TOKEN"]',
        "const apiKey = process.env.API_KEY;",
        "if (!token) throw new Error('missing token');",
        '<a href="#top">맨 위로</a>',
        "name: build\non:\n  push:\n    branches: [main]",
        "pip install -r requirements.txt",
        "| 이름 | 값 |\n|---|---|\n| 가 | 1 |",
        "```python\nprint('hello')\n```",
        "self.access_token = None",
        "access_token: Optional[str] = None",
        "def refresh_token(self): return self._refresh_token",
        "refresh_token_expires_in: 604800",
        "getAuthorizationHeaderFromRequestContext",
        "get_access_token_from_environment_variable()",
        "token_type=bearer",
        "Authorization: Basic dXNlcjpwYXNz",
        # 자리표(모양을 다 갖추지 않은 예시)
        "AIza…",
        "AIzaSy...",
        "ghp_xxxx",
        "Bearer <토큰>",
        "Bearer <your-token>",
        "AKIA<…>",
        "AKIA" + "X" * 10,
        "-----BEGIN",
        "-----BEGIN CERTIFICATE-----",
        "-----BEGIN PUBLIC KEY-----",
        "-----BEGIN PGP PUBLIC KEY BLOCK-----",
        "-----END RSA " + "PRIVATE KEY-----",
        "-----BEGIN PRIVATE-----",
        "----BEGIN " + "PRIVATE KEY----",
        "access_token=<토큰>",
        "access_token = None",
        "refresh_token: (비워 둠)",
        "Authorization: Bearer ${ACCESS_TOKEN}",
        "Bearer {{ token }}",
        "Bearer token",
        "bearer 토큰: 로그인 뒤에 받아요",
        "Bearer\n" + S.bearer_value(),
        "ya29.…",
        "eyJ…",
        "github_pat_…",
        "1//…",
        "YOUR_API_KEY",
        "sk-...",
        "aws_access_key_id = <여기에 입력>",
        "akia" + "iosfodnn7example",
        "MYAKIA" + "IOSFODNN7EXAMPL",
        # 숫자·기호·기타
        "전화 010-1234-5678, 날짜 2026-11-11, 가격 12,300원",
        "👍 좋아요 ✅ 완료 ⚠️ 주의",
        "ID: 20261111-ABCDEFG",
        "someone@example.com 으로 메일 주세요",
    ]
    items += [text for _, text in short_of]
    return tuple(items)


class FalsePositiveTest(Base):
    def test_a_hundred_normal_texts_are_not_flagged(self):
        texts = clean_texts()
        self.assertGreaterEqual(len(texts), 100)
        self.assertEqual(len(set(texts)), len(texts), "겹치는 표본이 있다")
        for number, text in enumerate(texts):
            with self.subTest(number=number):
                self.assert_none(text, f"{number}번 표본")

    def test_the_short_of_the_limit_samples_are_clean_but_one_more_character_is_a_finding(self):
        cases = (("google_api_key", lambda n: "AI" + "za" + S.body(n, S.B64URL, 3), 35), ("github_token", lambda n: S.github("p", n), 36), ("oauth_token", lambda n: S.ya29(n), 20),
                 ("oauth_token", lambda n: S.refresh(n), 20), ("aws_access_key", lambda n: S.aws("AKIA", n), 16))
        for kind, make, limit in cases:
            with self.subTest(kind + str(limit)):
                self.assert_none("x " + make(limit - 1))
                token = make(limit)
                self.assert_one("x " + token, kind, token)

    def test_the_two_real_posts_in_the_fixtures_are_clean(self):
        for name in ("chance_post_en.md", "chance_post_ko.md"):
            with self.subTest(name):
                text = (ROOT / "tests" / "fixtures" / name).read_text(encoding="utf-8")
                self.assertGreater(len(text), 2000)
                self.assert_none(text, name)

    def test_long_ordinary_texts_in_both_languages_are_clean_and_every_line_of_them(self):
        text = (PROSE * 600) + "\n" + ("토큰과 Bearer 와 API 키 이야기 — access token 과 refresh_token 이라는 이름만 나온다.\n" * 200)
        self.assert_none(text)
        for line in text.splitlines()[:50]:
            self.assertFalse(scan.has_secret(line))


# ---- 2) 미탐 표 -------------------------------------------------------------------------------------------------------------------
def variants():
    found = [("google_api_key", "google", "", S.google())]
    found += [("github_token", "gh" + letter + "_", "", S.github(letter)) for letter in "pousr"]
    found += [("github_token", "github_pat_", "", S.github_pat()), ("bearer_token", "Bearer", "Bearer ", S.bearer_value()), ("oauth_token", "ya29.", "", S.ya29()), ("oauth_token", "1//", "", S.refresh()),
              ("oauth_token", "GOCSPX-", "", S.gocspx()), ("oauth_token", "jwt", "", S.jwt()), ("oauth_token", "access_token=", "access_token=", S.body(30, S.B64URL, 8)), ("oauth_token", "refresh_token: ", 'refresh_token": "', S.body(28, S.B64URL, 2)),
              ("oauth_token", "accessToken:", "accessToken: ", S.body(24, S.B64URL, 5))]
    found += [("aws_access_key", prefix, "", S.aws(prefix)) for prefix in ("AKIA", "ASIA", "AGPA", "AIDA", "AROA", "ANPA", "ANVA", "AIPA")]
    found += [("pem_private_key", "pem " + (kind.strip() or "none"), "", S.pem(kind)) for kind in ("", "RSA ", "EC ", "DSA ", "OPENSSH ", "ENCRYPTED ")]
    return tuple(found)


CONTEXTS = (
    ("그대로", lambda lead, t: lead + t),
    ("줄 끝(LF)", lambda lead, t: "앞 줄\n" + lead + t + "\n뒷 줄"),
    ("글 끝", lambda lead, t: "앞 줄\n" + lead + t),
    ("글 처음", lambda lead, t: lead + t + "\n뒷 줄"),
    ("큰따옴표 안", lambda lead, t: '값은 "' + lead + t + '" 입니다'),
    ("작은따옴표 안", lambda lead, t: "값은 '" + lead + t + "' 입니다"),
    ("역따옴표 안", lambda lead, t: "값은 `" + lead + t + "` 입니다"),
    ("JSON 안", lambda lead, t: '{"name": "x", "value": "' + lead + t + '", "n": 1}'),
    ("URL 질의 안", lambda lead, t: "example.com/api?x=1&k=" + (lead.replace(" ", "%20") if lead.startswith("Bearer") else lead) + t + "&y=2"),
    ("마크다운 코드 블록 안", lambda lead, t: "설명\n\n```\n" + lead + t + "\n```\n\n끝"),
    ("소괄호", lambda lead, t: "(" + lead + t + ")"),
    ("대괄호", lambda lead, t: "[" + lead + t + "]"),
    ("꺾쇠", lambda lead, t: "<" + lead + t + ">"),
    ("쉼표", lambda lead, t: lead + t + ", 다음"),
    ("마침표", lambda lead, t: "값은 " + lead + t + "."),
    ("느낌표", lambda lead, t: lead + t + "!"),
    ("굵게", lambda lead, t: "**" + lead + t + "**"),
    ("CRLF", lambda lead, t: "앞 줄\r\n" + lead + t + "\r\n뒷 줄"),
    ("탭", lambda lead, t: "키\t=\t" + lead + t + "\t끝"),
    ("긴 글 한가운데", lambda lead, t: PROSE * 30 + "\n" + lead + t + "\n" + PROSE * 30),
    ("한글 조사 붙음", lambda lead, t: "토큰은" + lead + t + "입니다"),
    ("퍼센트 인코딩 구분자 뒤", lambda lead, t: "x?k%3D" + (lead.replace(" ", "%20") if lead.startswith("Bearer") else lead) + t + "&y%3D2"),
)


class FalseNegativeTest(Base):
    def test_every_variant_in_every_context_is_one_exact_finding(self):
        count = 0
        for kind, label, lead, token in variants():
            for context, build in CONTEXTS:
                text = build(lead, token)
                with self.subTest(f"{label} / {context}"):
                    self.assert_one(text, kind, token)
                    self.assertTrue(scan.has_secret(text))
                count += 1
        self.assertEqual(len(variants()), 29)
        self.assertEqual(count, len(variants()) * len(CONTEXTS))
        self.assertEqual(count, 29 * len(CONTEXTS))
        self.assertEqual(len(CONTEXTS), 22)

    def test_the_variants_cover_all_six_kinds_and_every_prefix_and_form_the_brief_names(self):
        self.assertEqual({kind for kind, *_ in variants()}, set(scan.KINDS))
        labels = {label for _, label, _, _ in variants()}
        for needed in ("google", "ghp_", "gho_", "ghu_", "ghs_", "ghr_", "github_pat_", "Bearer", "ya29.", "1//", "GOCSPX-", "jwt", "access_token=", "AKIA", "ASIA", "AGPA", "AIDA", "AROA", "ANPA", "ANVA", "AIPA", "pem none", "pem RSA", "pem EC", "pem DSA", "pem OPENSSH", "pem ENCRYPTED"):
            self.assertIn(needed, labels)

    def test_a_pgp_block_header_a_lowercase_header_and_wide_spaces_are_found_too(self):
        for header in ("-----" + "BEGIN PGP " + "PRIVATE KEY BLOCK-----", "-----" + "begin rsa " + "private key-----", "-----" + "BEGIN  RSA  " + "PRIVATE  KEY-----", "-----" + "BEGIN\tEC\t" + "PRIVATE\tKEY-----",
                       "-----" + "BEGIN RSA " + "PRIVATE KEY -----", "-----" + "BEGIN A B C " + "PRIVATE KEY-----"):
            with self.subTest(header[:24]):
                self.assert_one("앞\n" + header + "\n뒤", "pem_private_key", header)

    def test_findings_in_a_long_mixed_text_are_all_found_once_each_in_order(self):
        parts = [(kind, lead + token, token) for kind, _, lead, token in variants()[:14]]
        text = ""
        for index, (kind, shown, token) in enumerate(parts):
            text += PROSE * 3 + f"\n항목 {index}: {shown}\n"
        result = scan.scan_secrets(text)
        self.assertEqual([item.kind for item in result], [kind for kind, _, _ in parts])
        lines = text.split("\n")
        for item, (kind, shown, token) in zip(result, parts):
            self.assertTrue(lines[item.line - 1][item.col_start - 1:item.col_end] == token, "자리의 글이 표본과 다르다")

    def test_a_token_next_to_korean_letters_with_no_space_is_found(self):
        for kind, label, lead, token in variants():
            with self.subTest(label):
                self.assert_one("키는" + lead + token + "이에요", kind, token)


# ---- 3) 경계값 --------------------------------------------------------------------------------------------------------------------
NON_CLASS = tuple(".+/=!@#$%^&*()[]{}<>?,;:'\"\\|`" + " \t") + ("가", "é", chr(0x200B), chr(0x301), "😀")
LEFT_OK = ("_", "-", ".", ":", "=", "/", '"', "'", "(", " ", "\t", "\n", "\r", "가", "…", BOM, chr(0x200B), "😀", "[", "{", "<", ",", ";", "*", "`")


class GoogleBoundaryTest(Base):
    def test_the_body_length_limit_is_thirty_five_and_longer_runs_are_one_finding(self):
        for length, kind in ((0, None), (1, None), (33, None), (34, None), (35, "google_api_key"), (36, "google_api_key"), (60, "google_api_key"), (500, "google_api_key")):
            token = "AI" + "za" + S.body(length, S.B64URL, 3)
            with self.subTest(length):
                if kind:
                    self.assert_one("k=" + token, kind, token)
                else:
                    self.assert_none("k=" + token)

    def test_every_body_character_counts_at_the_start_the_middle_and_the_end(self):
        for ch in S.B64URL:
            for position in (0, 17, 34):
                body = ["a"] * 35
                body[position] = ch
                token = "AI" + "za" + "".join(body)
                with self.subTest(ch + str(position)):
                    self.assert_one("k " + token, "google_api_key", token)

    def test_a_character_outside_the_class_in_the_middle_breaks_the_run_in_two_short_runs(self):
        for ch in NON_CLASS:
            with self.subTest(repr(ch)):
                self.assert_none("AI" + "za" + "a" * 17 + ch + "a" * 17)

    def test_the_prefix_is_exact_in_case_and_letters(self):
        for prefix in ("aIza", "AIZA", "AlZa", "AIzA", "Alza", "AIz", "Iza", "AIzb", "BIza", "AIza".lower(), "AIza".upper()):
            with self.subTest(prefix):
                self.assert_none("k=" + prefix + S.body(35, S.B64URL))

    def test_the_letter_in_front_decides_but_punctuation_korean_and_invisible_characters_do_not(self):
        token = S.google()
        for ch in string.ascii_letters + string.digits:
            with self.subTest("앞에 " + ch):
                self.assert_none(ch + token)
        for ch in LEFT_OK:
            with self.subTest("앞에 " + repr(ch)):
                self.assert_one(ch + token, "google_api_key", token)


class GithubBoundaryTest(Base):
    def test_the_five_classic_letters_are_found_and_other_letters_and_cases_are_not(self):
        for letter in "pousr":
            token = S.github(letter)
            with self.subTest(letter):
                self.assert_one("t " + token, "github_token", token)
        for letter in "abcdefghijklmnqtvwxyzPOUSR0_ ":
            with self.subTest("글자 " + repr(letter)):
                self.assert_none("t " + "gh" + letter + "_" + S.body(40, S.ALNUM))
        for prefix in ("GHP_", "Ghp_", "gHp_", "ghp", "gp_", "hp_", "ghp-", "ghp__", "ghp "):
            with self.subTest(prefix):
                self.assert_none("t " + prefix + S.body(40, S.ALNUM))

    def test_classic_body_length_limit_is_thirty_six(self):
        for length, found in ((35, False), (36, True), (37, True), (255, True)):
            token = S.github("p", length)
            with self.subTest(length):
                if found:
                    self.assert_one("t " + token, "github_token", token)
                else:
                    self.assert_none("t " + token)

    def test_classic_body_is_letters_and_digits_only(self):
        for ch in S.ALNUM:
            for position in (0, 18, 35):
                body = ["a"] * 36
                body[position] = ch
                token = "gh" + "p_" + "".join(body)
                with self.subTest(ch + str(position)):
                    self.assert_one("t " + token, "github_token", token)
        for ch in ("_", "-", ".", "/", "+", "=", " ", "가"):
            with self.subTest("끊김 " + repr(ch)):
                self.assert_none("t " + "gh" + "p_" + "a" * 18 + ch + "a" * 17)

    def test_fine_grained_token_length_limit_is_twenty_two_and_its_body_may_hold_underscores(self):
        for length, found in ((21, False), (22, True), (23, True), (82, True)):
            token = S.github_pat(length)
            with self.subTest(length):
                if found:
                    self.assert_one("t " + token, "github_token", token)
                else:
                    self.assert_none("t " + token)
        underscored = "github_" + "pat_" + "a" * 10 + "_" + "b" * 11
        self.assert_one("t " + underscored, "github_token", underscored)
        for ch in ("-", ".", " ", "가"):
            with self.subTest(repr(ch)):
                self.assert_none("t " + "github_" + "pat_" + "a" * 10 + ch + "b" * 11)
        for prefix in ("GITHUB_PAT_", "github_pat", "githubpat_", "github-pat-", "Github_pat_"):
            with self.subTest(prefix):
                self.assert_none("t " + prefix + S.body(40, S.ALNUM))

    def test_a_letter_or_digit_in_front_is_not_a_token_but_an_underscore_is_allowed(self):
        for token in (S.github(), S.github_pat()):
            for ch in string.ascii_letters + string.digits:
                with self.subTest(token[:3] + ch):
                    self.assert_none(ch + token)
            for ch in LEFT_OK:
                with self.subTest(token[:3] + repr(ch)):
                    self.assert_one(ch + token, "github_token", token)


class BearerBoundaryTest(Base):
    def test_the_word_is_case_insensitive_and_needs_a_separator(self):
        value = S.bearer_value()
        for word in ("Bearer", "bearer", "BEARER", "BeArEr", "bEARER"):
            with self.subTest(word):
                self.assert_one(word + " " + value, "bearer_token", value)
        for sep in (" ", "  ", "\t", " \t ", "%20", "+", "\t\t\t"):
            with self.subTest(repr(sep)):
                self.assert_one("Bearer" + sep + value, "bearer_token", value)
        for sep in ("", "\n", "\r\n", ":", "=", ",", "-", "_", "가", "%2", "\n ", ". "):
            with self.subTest("구분 없음 " + repr(sep)):
                self.assert_none("Bearer" + sep + value)
        for word in ("Bearers", "Bearer-", "Bear", "Bea rer", "Berer", "Beare", "earer"):
            with self.subTest("낱말 " + word):
                self.assert_none(word + " " + value)

    def test_a_letter_in_front_of_the_word_is_not_the_word_but_a_digit_or_punctuation_is(self):
        value = S.bearer_value()
        for ch in string.ascii_letters:
            with self.subTest("앞에 " + ch):
                self.assert_none(ch + "Bearer " + value)
        for ch in string.digits + "_-.:=/\"'(가\n" + BOM:
            with self.subTest("앞에 " + repr(ch)):
                self.assert_one(ch + "Bearer " + value, "bearer_token", value)

    def test_value_length_limit_is_twenty_and_a_trailing_dot_is_not_part_of_it(self):
        for length, found in ((1, False), (10, False), (19, False), (20, True), (21, True), (64, True), (4000, True)):
            value = S.bearer_value(length)
            with self.subTest(length):
                if found:
                    self.assert_one("Bearer " + value, "bearer_token", value)
                else:
                    self.assert_none("Bearer " + value)
        self.assert_none("Bearer " + "a" * 19 + ".")
        self.assert_one("Bearer " + "a" * 20 + ".", "bearer_token", "a" * 20)
        self.assert_one("Bearer " + "a" * 25 + "...", "bearer_token", "a" * 25)

    def test_every_token_character_counts_inside_the_value_and_the_non_token_characters_stop_it(self):
        for ch in S.BEARER_CHARS:
            for position in (0, 9, 18):
                value = ["a"] * 19 + ["k"]
                value[position] = ch
                value = "".join(value)
                with self.subTest(repr(ch) + str(position)):
                    self.assert_one("Bearer " + value, "bearer_token", value)
        for ch in "_-+/" + S.TILDE:
            value = "a" * 19 + ch
            with self.subTest("끝 " + repr(ch)):
                self.assert_one("Bearer " + value, "bearer_token", value)
        for ch in tuple("!@#$%^&*()[]{}<>?,;:'\"\\|` \t=") + ("가", "é", "😀"):
            with self.subTest("끊김 " + repr(ch)):
                self.assert_none("Bearer " + "a" * 10 + ch + "a" * 9 + "k")

    def test_up_to_two_equal_signs_of_padding_belong_to_the_value(self):
        value = S.bearer_value()
        for padding, kept in (("", ""), ("=", "="), ("==", "=="), ("===", "==")):
            with self.subTest(padding):
                self.assert_one("Bearer " + value + padding, "bearer_token", value + kept)

    def test_a_url_style_separator_after_the_word_works_and_the_value_stops_at_the_ampersand(self):
        value = S.bearer_value()
        text = "example.com/a?h=Bearer%20" + value + "&x=1"
        self.assert_one(text, "bearer_token", value)
        text = "example.com/a?h=Bearer+" + value + "&x=1"
        self.assert_one(text, "bearer_token", value)


class OauthBoundaryTest(Base):
    def test_google_access_token_length_limit_is_twenty_and_dots_stop_the_run(self):
        for length, found in ((10, False), (19, False), (20, True), (21, True), (200, True)):
            token = S.ya29(length)
            with self.subTest(length):
                if found:
                    self.assert_one("t=" + token, "oauth_token", token)
                else:
                    self.assert_none("t=" + token)
        self.assert_none("ya" + "29." + "a" * 10 + "." + "a" * 10)
        for prefix in ("YA29.", "ya28.", "ya29", "ya29-", "ya29_", "a29.", "ya9."):
            with self.subTest(prefix):
                self.assert_none("t=" + prefix + S.body(30, S.B64URL))

    def test_google_refresh_token_length_limit_is_twenty_and_the_prefix_is_exact(self):
        for length, found in ((10, False), (19, False), (20, True), (21, True), (200, True)):
            token = S.refresh(length)
            with self.subTest(length):
                if found:
                    self.assert_one("t=" + token, "oauth_token", token)
                else:
                    self.assert_none("t=" + token)
        for prefix in ("1/", "1///", "2//", "1" + chr(92) * 2, "1/ /", "11//"):
            with self.subTest(prefix):
                self.assert_none("t=" + prefix + S.body(30, S.B64URL))
        token = S.refresh()
        self.assert_one("a/" + token, "oauth_token", token)
        self.assert_none("a" + token)

    def test_every_token_character_counts_in_both_google_shapes(self):
        for make in (lambda body: "ya" + "29." + body, lambda body: "1/" + "/" + body):
            for ch in S.B64URL:
                for position in (0, 10, 19):
                    body = ["a"] * 20
                    body[position] = ch
                    token = make("".join(body))
                    with self.subTest(token[:3] + ch + str(position)):
                        self.assert_one("t=" + token, "oauth_token", token)

    def test_google_client_secret_length_limit_is_twenty_and_the_prefix_is_exact(self):
        for length, found in ((10, False), (19, False), (20, True), (28, True), (29, True), (200, True)):
            token = S.gocspx(length)
            with self.subTest(length):
                if found:
                    self.assert_one("t=" + token, "oauth_token", token)
                else:
                    self.assert_none("t=" + token)
        for prefix in ("GOCSPY-", "gocspx-", "Gocspx-", "GOCSPX_", "GOCSPX", "GOCSP-", "OCSPX-", "GOCSPXX-"):
            with self.subTest(prefix):
                self.assert_none("t=" + prefix + S.body(30, S.B64URL))
        for ch in S.B64URL:
            body = ["a"] * 28
            body[13] = ch
            token = "GOC" + "SPX-" + "".join(body)
            with self.subTest(ch):
                self.assert_one("t=" + token, "oauth_token", token)

    def test_the_left_neighbour_must_not_be_a_letter_or_a_digit_for_the_four_prefix_shapes(self):
        for token in (S.ya29(), S.refresh(), S.gocspx(), S.jwt()):
            for ch in string.ascii_letters + string.digits:
                with self.subTest(token[:3] + ch):
                    self.assert_none(ch + token)
            for ch in LEFT_OK:
                with self.subTest(token[:3] + repr(ch)):
                    self.assert_one(ch + token, "oauth_token", token)

    def test_jwt_needs_three_dotted_parts_with_the_first_two_starting_with_the_json_mark(self):
        for head, payload, signature, found in ((8, 4, 8, True), (7, 4, 8, False), (8, 3, 8, False), (8, 4, 7, False), (36, 24, 43, True), (400, 400, 400, True), (8, 4, 342, True)):
            token = S.jwt(head, payload, signature)
            with self.subTest((head, payload, signature)):
                if found:
                    self.assert_one("t " + token, "oauth_token", token)
                else:
                    self.assert_none("t " + token)
        head, payload, signature = "eyJ" + S.body(20, S.B64URL), "eyJ" + S.body(20, S.B64URL), S.body(20, S.B64URL)
        for text in (head + "." + payload, head + payload + "." + signature, head + "." + "xyJ" + S.body(20, S.B64URL) + "." + signature, "eyj" + head[3:] + "." + payload + "." + signature,
                     head + "." + payload + "-" + signature, head + "," + payload + "," + signature, head + ".." + signature):
            with self.subTest(text[:8] + str(len(text))):
                self.assert_none("t " + text)

    def test_jwt_parts_may_hold_underscores_and_hyphens_but_not_dots_or_plus_or_slash(self):
        token = "eyJ" + "a_b-" * 5 + "." + "eyJ" + "c_d-" * 3 + "." + "e_f-" * 4
        self.assert_one("t " + token, "oauth_token", token)
        for ch in ("+", "/", "=", " "):
            with self.subTest(repr(ch)):
                self.assert_none("t " + "eyJ" + "a" * 5 + ch + "a" * 5 + "." + "eyJ" + "b" * 10 + "." + "c" * 10)

    def test_named_values_work_for_every_name_form_separator_and_quote(self):
        value = S.body(30, S.B64URL, 8)
        for name in ("access_token", "refresh_token", "accessToken", "refreshToken", "ACCESS_TOKEN", "REFRESH_TOKEN", "Access-Token", "refresh-token", "access-Token", "AccessToken", "accesstoken"):
            for sep in ("=", ":", ": ", " = ", " : ", '": "', '":"', "': '", '" = "', "=>", ' => ', '"=>"', "\t=\t"):
                with self.subTest(name + sep):
                    self.assert_one("{" + name + sep + value + "}", "oauth_token", value)

    def test_named_value_length_limit_is_twenty_and_a_trailing_dot_is_not_part_of_it(self):
        for length, found in ((1, False), (10, False), (19, False), (20, True), (21, True), (100, True)):
            value = S.body(length, S.B64URL, 8)
            with self.subTest(length):
                if found:
                    self.assert_one("access_token=" + value, "oauth_token", value)
                else:
                    self.assert_none("access_token=" + value)
        self.assert_none("access_token=" + "a" * 19 + ".")
        self.assert_one("access_token=" + "a" * 20 + ".", "oauth_token", "a" * 20)
        self.assert_one("access_token=" + "a" * 10 + "." + "b" * 10, "oauth_token", "a" * 10 + "." + "b" * 10)
        self.assert_one("access_token=" + "a" * 25 + "...", "oauth_token", "a" * 25)

    def test_named_value_characters_and_padding(self):
        for ch in S.B64URL + "+/%.":
            for position in (0, 10, 18):
                value = ["a"] * 19 + ["k"]
                value[position] = ch
                value = "".join(value)
                with self.subTest(repr(ch) + str(position)):
                    self.assert_one("access_token=" + value, "oauth_token", value)
        for ch in ("_", "-", "+", "/", "%"):
            value = "a" * 19 + ch
            with self.subTest("끝 " + ch):
                self.assert_one("access_token=" + value, "oauth_token", value)
        value = S.body(30, S.B64URL, 8)
        for padding, kept in (("", ""), ("=", "="), ("==", "=="), ("===", "==="), ("====", "===")):
            with self.subTest(padding):
                self.assert_one("access_token=" + value + padding, "oauth_token", value + kept)
        for ch in tuple("!@#$^&*()[]{}<>?,;:'\"\\|` \t=") + ("가", "é"):
            with self.subTest("끊김 " + repr(ch)):
                self.assert_none("access_token=" + "a" * 10 + ch + "a" * 9 + "k")

    def test_other_names_and_shapes_around_the_name_do_not_count(self):
        value = S.body(30, S.B64URL, 8)
        for name in ("id_token", "token", "oauth_token", "access_tokens", "access_tok", "accesstoke", "access token", "access_  token", "access__token", "refresh token", "api_token", "bearer_token"):
            with self.subTest(name):
                self.assert_none(name + "=" + value)
        for text in ("access_token", "access_token=", "access_token:", "access_token= ", "access_token=\n" + value, "access_token\n=" + value, "access_token ;" + value, "access_token.=" + value):
            with self.subTest(repr(text[:16])):
                self.assert_none(text)
        self.assert_one("userAccessToken: " + value, "oauth_token", value)
        self.assert_one("OAUTH_ACCESS_TOKEN=" + value, "oauth_token", value)
        self.assert_one("myaccess_token=" + value, "oauth_token", value)

    def test_the_quotes_around_name_and_value_are_optional_and_not_part_of_the_value(self):
        value = S.body(30, S.B64URL, 8)
        for text in ("access_token=" + value, 'access_token="' + value + '"', "access_token='" + value + "'", '"access_token"="' + value + '"', "'access_token':'" + value + "'", "access_token: " + value, 'access_token : "' + value + '"'):
            with self.subTest(text[:18]):
                self.assert_one(text, "oauth_token", value)


class AwsBoundaryTest(Base):
    def test_the_eight_prefixes_are_found_and_look_alikes_are_not(self):
        for prefix in ("AKIA", "ASIA", "AGPA", "AIDA", "AROA", "ANPA", "ANVA", "AIPA"):
            token = S.aws(prefix)
            with self.subTest(prefix):
                self.assert_one("id " + token, "aws_access_key", token)
        for prefix in ("ABIA", "ACCA", "ASCA", "AKIB", "AKIC", "BKIA", "AKI", "KIA", "AXIA", "AIDB", "ROA", "akia", "Akia", "AKia", "aKIA", "ASIB", "AGPB", "AROB", "ANPB", "ANVB", "AIPB"):
            with self.subTest(prefix):
                self.assert_none("id " + prefix + S.body(20 - len(prefix), S.UPPER_DIGITS, 35))

    def test_the_body_is_exactly_sixteen_uppercase_letters_or_digits(self):
        for length, found in ((14, False), (15, False), (16, True), (17, False), (18, False), (40, False)):
            token = S.aws("AKIA", length)
            with self.subTest(length):
                if found:
                    self.assert_one("id " + token, "aws_access_key", token)
                else:
                    self.assert_none("id " + token)
        for ch in S.UPPER_DIGITS:
            for position in (0, 7, 15):
                body = ["A"] * 16
                body[position] = ch
                token = "AK" + "IA" + "".join(body)
                with self.subTest(ch + str(position)):
                    self.assert_one("id " + token, "aws_access_key", token)
        for ch in string.ascii_lowercase + "_-+/=.":
            with self.subTest("몸 안의 " + ch):
                self.assert_none("id AK" + "IA" + "A" * 7 + ch + "A" * 8)

    def test_the_neighbours_must_not_be_letters_or_digits_on_either_side(self):
        token = S.aws()
        for ch in string.ascii_letters + string.digits:
            with self.subTest("앞 " + ch):
                self.assert_none(ch + token)
            with self.subTest("뒤 " + ch):
                self.assert_none(token + ch)
        for ch in LEFT_OK:
            with self.subTest("앞 " + repr(ch)):
                self.assert_one(ch + token, "aws_access_key", token)
            with self.subTest("뒤 " + repr(ch)):
                self.assert_one(token + ch, "aws_access_key", token)
        self.assert_one(token + "_x", "aws_access_key", token)
        self.assert_one("_" + token, "aws_access_key", token)
        self.assert_one(token + "입니다", "aws_access_key", token)


class PemBoundaryTest(Base):
    def test_the_header_needs_five_dashes_begin_private_key_and_closing_dashes(self):
        good = S.pem("RSA ")
        self.assert_one(good, "pem_private_key", good)
        for text in ("-----" + "BEGIN RSA " + "PRIVATE KEY----", "----" + "BEGIN RSA " + "PRIVATE KEY-----", "-----" + "BEGIN RSA " + "PRIVATE KEY", "-----" + "BEGIN RSA " + "PRIVATE-----",
                     "-----" + "BEGIN RSA " + "KEY-----", "-----" + "BEGINRSA " + "PRIVATE KEY-----", "-----" + "BEGIN RSA " + "PRIVATEKEY-----", "-----" + "BEGIN RSA " + "PRIVATE  " + "KEYS-----",
                     "-----" + "END RSA " + "PRIVATE KEY-----", "-----" + "BEGIN PUBLIC KEY-----", "-----" + "BEGIN CERTIFICATE-----", "-----" + "BEGIN RSA PUBLIC KEY-----", "- - - - -BEGIN RSA PRIVATE KEY- - - - -",
                     "-----" + "BEGIN\nRSA " + "PRIVATE KEY-----", "-----" + "BEGIN RSA\n" + "PRIVATE KEY-----"):
            with self.subTest(text[:30].replace("\n", "|")):
                self.assert_none(text)

    def test_up_to_three_words_may_sit_between_begin_and_private_key_but_not_four(self):
        for words in ("", "A ", "A B ", "A B C ", "RSA ", "OPENSSH ", "ENCRYPTED ", "PGP ", "EC ", "DSA ", "X1 Y2 Z3 "):
            header = "-----" + "BEGIN " + words + "PRIVATE KEY-----"
            with self.subTest(words):
                self.assert_one("t " + header, "pem_private_key", header)
        self.assert_none("-----" + "BEGIN A B C D " + "PRIVATE KEY-----")
        self.assert_none("-----" + "BEGIN a-b " + "PRIVATE KEY-----")

    def test_a_block_word_after_key_and_spaces_before_the_closing_dashes_are_allowed(self):
        for tail in ("KEY-----", "KEY BLOCK-----", "KEY  BLOCK -----", "KEY\t-----", "KEY BLOCK\t-----"):
            header = "-----" + "BEGIN PGP " + "PRIVATE " + tail
            with self.subTest(tail):
                self.assert_one(header, "pem_private_key", header)
        self.assert_none("-----" + "BEGIN PGP " + "PRIVATE KEY BLOCKS-----")
        self.assert_none("-----" + "BEGIN PGP " + "PRIVATE KEY BLOCK BLOCK-----")

    def test_the_header_is_found_wherever_it_stands_even_glued_to_other_text(self):
        header = S.pem("RSA ")
        for lead, tail in (("글" + "", "글"), ("a", "b"), ("1", "2"), ("-", "-"), ("=", ""), ('"', '"'), ("\n", "\r\n"), ("\t", "\t")):
            with self.subTest(repr(lead) + repr(tail)):
                text = lead + header + tail
                self.assertEqual(self.found(text), [("pem_private_key", *S.locate(text, header))])
        six = "-" + header
        self.assertEqual(len(scan.scan_secrets(six)), 1)


class PercentEscapeTest(Base):
    NAMED = ("access_token=", 'refresh_token": "', "accessToken: ")

    def test_a_percent_escape_right_in_front_is_a_boundary_for_every_prefix_shape(self):
        for kind, label, lead, token in variants():
            if lead in self.NAMED:
                continue
            for escape in ("%3D", "%3d", "%20", "%2F", "%22", "%27", "%0A", "%26", "%3A", "%00", "%FF", "%aB"):
                with self.subTest(label + escape):
                    self.assert_one("x" + escape + lead + token, kind, token)

    def test_something_that_only_looks_like_an_escape_is_not_a_boundary(self):
        for kind, label, lead, token in variants():
            if lead in self.NAMED or kind == "pem_private_key":          # 이름 붙은 값과 PEM 머리 줄은 앞 글자를 보지 않는다
                continue
            fakes = ("%3G", "3D", "ab", "%G3", "%3D3", "%3", "%A", "D3") if lead != "Bearer " else ("%3G", "3D", "ab", "xD")
            for fake in fakes:
                with self.subTest(label + fake):
                    self.assert_none("x" + fake + lead + token)

    def test_a_plain_percent_sign_in_front_is_still_a_boundary_and_a_value_runs_up_to_an_ampersand(self):
        token = S.github()
        self.assert_one("100%" + token, "github_token", token)
        value = S.body(30, S.B64URL, 8)
        self.assert_one("a=1&access_token=" + value + "&b%3D2", "oauth_token", value)


# ---- 4) 글자 맞추기와 알려진 한계 -----------------------------------------------------------------------------------------------------
def wide(text):
    return "".join(chr(ord(ch) + 0xFEE0) if "!" <= ch <= chr(126) else ch for ch in text)


class FoldTest(Base):
    def test_fullwidth_versions_of_every_kind_are_found_with_the_same_columns(self):
        for kind, label, lead, token in variants():
            if kind == "pem_private_key":
                continue
            with self.subTest(label):
                text = "앞 " + wide(lead) + wide(token) + " 뒤"
                found = scan.scan_secrets(text)
                self.assertEqual([item.kind for item in found], [kind])
                self.assertEqual((found[0].line, found[0].col_start, found[0].col_end), S.locate(text, wide(token)))

    def test_a_fullwidth_pem_header_is_found_when_the_spaces_are_ideographic_or_ascii(self):
        header = "-----" + "BEGIN RSA " + "PRIVATE KEY-----"
        for text in (wide(header), header.replace(" ", chr(0x3000)), header.replace(" ", chr(0xA0)), header.replace(" ", chr(0x2003))):
            with self.subTest(repr(text[:8])):
                self.assertEqual(S.triples(scan.scan_secrets("앞\n" + text)), [("pem_private_key", 2, 1, len(header))])

    def test_math_alphanumeric_letters_are_folded_one_for_one_in_code_points(self):
        bold = {ch: chr(0x1D400 + ord(ch) - 65) for ch in string.ascii_uppercase}
        bold.update({ch: chr(0x1D41A + ord(ch) - 97) for ch in string.ascii_lowercase})
        token = S.google()
        text = "앞 " + "".join(bold.get(ch, ch) for ch in token) + " 뒤"
        self.assertEqual(S.triples(scan.scan_secrets(text)), [("google_api_key", 1, 3, 2 + len(token))])
        self.assertEqual(len(scan._fold(text)), len(text))

    def test_special_spaces_between_bearer_and_the_value_count_as_a_space(self):
        value = S.bearer_value()
        for code in (0xA0, 0x2002, 0x2003, 0x2009, 0x202F, 0x205F, 0x3000):
            with self.subTest(hex(code)):
                text = "Bearer" + chr(code) + value
                self.assert_one(text, "bearer_token", value)
        self.assert_none("Bearer" + chr(0x200B) + value)
        self.assert_none("Bearer" + chr(0xFEFF) + value)

    def test_superscript_and_circled_digits_in_a_value_are_folded(self):
        digits = {"2": chr(0xB2), "3": chr(0xB3), "1": chr(0xB9)}
        token = "AK" + "IA" + "ABCDEF" + "123" + "GHIJKLM"
        self.assertEqual(len(token), 20)
        text = "id " + "".join(digits.get(ch, ch) for ch in token)
        self.assertEqual(S.triples(scan.scan_secrets(text)), [("aws_access_key", 1, 4, 23)])

    def test_the_fold_changes_nothing_that_is_plain_ascii_or_korean(self):
        for text in ("plain text 123", "가나다라 마바사", "한글 Hangul 混合", "emoji 😀 text"):
            self.assertEqual(scan._fold(text), text)
        self.assertIs(scan._fold("ascii only"), "ascii only")

    def test_known_limits_that_are_not_found_and_are_documented(self):
        token = S.github()
        half = len(token) // 2
        limits = {
            "공백으로 쪼갠 토큰": token[:half] + " " + token[half:],
            "줄바꿈으로 쪼갠 토큰": token[:half] + "\n" + token[half:],
            "보이지 않는 글자로 쪼갠 토큰": token[:half] + chr(0x200B) + token[half:],
            "소프트 하이픈으로 쪼갠 토큰": token[:half] + chr(0xAD) + token[half:],
            "접두어 앞에 영문이 붙은 토큰": "x" + token,
            "접두어 앞에 숫자가 붙은 토큰": "7" + token,
            "여섯 가지 밖의 형식(sk-)": "s" + "k-" + S.body(48, S.ALNUM),
            "여섯 가지 밖의 형식(Slack)": "xo" + "xb-" + "1234567890-" + S.body(24, S.ALNUM),
            "여섯 가지 밖의 형식(AWS 비밀 키 40자)": S.body(40, S.ALNUM + "/+"),
            "여섯 가지 밖의 형식(텔레그램)": "123456789:" + "AA" + S.body(33, S.B64URL),
            "PEM 몸통만(머리 없음)": "MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQC" + "x" * 60,
            "PEM 끝 줄만": "-----" + "END RSA " + "PRIVATE KEY-----",
            "Bearer 와 값이 다른 줄": "Bearer\n" + S.bearer_value(),
            "Bearer 와 값 사이 글자 하나": "Bearer: " + S.bearer_value(),
            "퍼센트로 적은 구분자 뒤의 이름 붙은 모르는 모양 값": "access_token%3D" + S.body(30, S.B64URL, 8),
        }
        for name, text in limits.items():
            with self.subTest(name):
                self.assert_none(text, name)


if __name__ == "__main__":
    unittest.main()
