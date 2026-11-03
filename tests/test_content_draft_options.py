"""작성 선택 입력(`content/draft_options.py` 의 `DraftOptions`) 시험.

지키는 것:
  1) 11칸(직접 전달하고 싶은 내용·실제 사용 경험·개인 의견·반드시 포함할 문장·제외할 내용·특정 독자층·원하는 글 길이·원하는 제목 방향·참고 URL·실제 가격이나 날짜·최종 결론)은 **모두 선택**이다 —
     아무것도 안 적어도(빈 글·빈 목록·None) 오류가 아니고 `is_empty()` 다.
  2) 글칸은 한 줄로 정리하고(공백 접기·제어·보이지 않는 글자 지움) 길이 상한(경계 포함)을 지킨다. 눈에 안 보이거나 쌓인 글자·위험한 HTML·템플릿 표기·결과를 약속하는 표현은 거절하되,
     경험을 단정하는 말은 막지 않는다(사용자의 글이다). 목록 칸은 빈 항목을 버리고 겹치는 것을 하나로 하며 개수 상한이 있다.
  3) 참고 URL 은 https 공개 주소만: http·javascript:·data:·file:·로그인 정보·토큰 인자·IP 주소·점 없는 이름·공백·따옴표·너무 긴 주소를 거절한다. 열거나 가져오지 않는다(네트워크를 쓰지 않는다).
  4) 글 길이는 `1500-2000`·`2500+` 모양의 숫자 범위만(200~100,000자, 하한 ≤ 상한).
  5) JSON 으로 저장·불러온 값이 같고 모르는 키·어긋난 값은 거절한다. 오류는 `DRAFT_OPTION_INVALID` 이고 문구에 어느 칸이 왜 안 되는지 담긴다.
네트워크·파일 없이 돈다.
"""
import socket
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from chanceblog_desktop.content import draft_options as do  # noqa: E402
from chanceblog_desktop.content.draft_options import DraftOptions, LengthWish, parse_length  # noqa: E402
from chanceblog_desktop.errors import AppError  # noqa: E402

TEXT_FIELDS = ("message", "experience", "opinion", "audience", "title_direction", "conclusion")
LIMITS = {"message": 500, "experience": 1000, "opinion": 500, "audience": 100, "title_direction": 100, "conclusion": 300}      # 문서(DECISIONS D-27)에 적힌 숫자 그대로


def refused(**fields):
    with unittest.TestCase().assertRaises(AppError) as caught:
        DraftOptions(**fields)
    return caught.exception


class EveryFieldIsOptionalTest(unittest.TestCase):
    def test_eleven_fields_with_distinct_korean_names(self):
        self.assertEqual(len(do.KEYS), 11)
        self.assertEqual(set(do.KEYS), set(do.LABELS))
        self.assertEqual(len(set(do.LABELS.values())), 11)
        self.assertEqual(set(do.KEYS), {"message", "experience", "opinion", "must_include", "exclude", "audience", "length", "title_direction", "urls", "price_date", "conclusion"})
        from dataclasses import fields
        self.assertEqual([item.name for item in fields(DraftOptions)], list(do.KEYS))

    def test_nothing_given_is_fine_and_empty(self):
        options = DraftOptions()
        self.assertTrue(options.is_empty())
        self.assertFalse(options.has_experience)
        self.assertEqual(options.user_texts(), ())
        for name in do.KEYS:
            self.assertFalse(getattr(options, name), name)

    def test_empty_values_in_every_shape_are_the_same_as_nothing(self):
        options = DraftOptions(message="", experience="   ", opinion="\n", must_include=(), exclude=[], audience="\t", length=None, title_direction="", urls=(), price_date=[], conclusion="")
        self.assertEqual(options, DraftOptions())
        self.assertEqual(DraftOptions(length=""), DraftOptions())
        self.assertEqual(DraftOptions(must_include=["", "  "], exclude=("",), urls=["", " "], price_date=[""]), DraftOptions())

    def test_each_single_field_alone_makes_it_non_empty(self):
        samples = {"message": "전하고 싶은 말", "experience": "써 본 경험", "opinion": "의견", "must_include": ["꼭 넣을 문장"], "exclude": ["광고"], "audience": "직장인", "length": "1500-2000",
                   "title_direction": "질문형", "urls": ["https://example.com/a"], "price_date": ["12,000원"], "conclusion": "결론"}
        self.assertEqual(set(samples), set(do.KEYS))
        for name, value in samples.items():
            with self.subTest(field=name):
                options = DraftOptions(**{name: value})
                self.assertFalse(options.is_empty())
                self.assertTrue(getattr(options, name))

    def test_user_texts_collects_every_text_but_not_urls(self):
        options = DraftOptions(message="가", experience="나다라", opinion="마", must_include=("바", "사"), exclude=("아",), audience="자", title_direction="차", urls=["https://example.com"], price_date=("카",), conclusion="타")
        self.assertEqual(set(options.user_texts()), {"가", "나다라", "마", "바", "사", "아", "자", "차", "카", "타"})       # 제외할 내용도 사용자가 적은 글이다
        self.assertTrue(DraftOptions(experience="경험").has_experience)


class TextFieldTest(unittest.TestCase):
    def test_text_is_folded_to_one_line_and_invisible_characters_are_dropped(self):
        for name in TEXT_FIELDS:
            with self.subTest(field=name):
                options = DraftOptions(**{name: "  앞뒤\t공백이\n  있는   글\u200b입니다 \u202e"})
                self.assertEqual(getattr(options, name), "앞뒤 공백이 있는 글입니다")

    def test_every_character_the_mask_hides_is_dropped_or_named_as_invisible_never_called_a_password(self):
        from chanceblog_desktop.security import mask as secret_mask
        hidden = [chr(code) for code in range(0x110000) if secret_mask._INVISIBLE.fullmatch(chr(code))]
        self.assertGreater(len(hidden), 4000)
        wrong = []
        for char in hidden:
            try:
                DraftOptions(message="보일러 점검" + char + "순서 안내")
            except AppError as error:
                if "눈에 보이지 않거나" not in error.slots["이유"]:
                    wrong.append((hex(ord(char)), error.slots["이유"][:20]))
        self.assertEqual(wrong, [])

    def test_the_rare_invisible_characters_get_the_invisible_character_reason(self):
        for code in (0x2065, 0xFFF0, 0xFFF8, 0xE0000, 0xE0100, 0xE0FFF):
            with self.subTest(code=hex(code)):
                reason = refused(message="보일러 점검" + chr(code) + "순서 안내").slots["이유"]
                self.assertIn("눈에 보이지 않거나", reason)
                self.assertNotIn("비밀번호", reason)
        self.assertEqual(DraftOptions(message="보일러 점검" + chr(0x200B) + "순서 안내").message, "보일러 점검순서 안내", "흔한 보이지 않는 글자는 예전처럼 지운다")

    def test_length_limits_are_inclusive(self):
        for name, high in LIMITS.items():
            with self.subTest(field=name):
                self.assertEqual(len(getattr(DraftOptions(**{name: "가" * high}), name)), high)
                error = refused(**{name: "가" * (high + 1)})
                self.assertEqual(error.code, "DRAFT_OPTION_INVALID")
                self.assertEqual(error.slots["항목"], do.LABELS[name])
                self.assertIn(f"{high}자 이하", error.slots["이유"])

    def test_the_limit_counts_after_cleaning(self):
        high = LIMITS["message"]
        padded = "가" * high + " " * 50 + "\u200b" * 50
        self.assertEqual(len(DraftOptions(message=padded).message), high)

    def test_non_text_values_are_refused(self):
        for name in TEXT_FIELDS:
            for value in (5, 1.5, ["가"], ("가",), {"가": 1}, b"abc", True):
                with self.subTest(field=name, value=value):
                    self.assertEqual(refused(**{name: value}).code, "DRAFT_OPTION_INVALID")

    def test_invisible_lookalike_and_stacked_characters_are_refused(self):
        for name in TEXT_FIELDS:
            for bad in ("가\u3164나", "가\u2800나", "가\u115f나", "가�나", "가\u0301\u0302\u0303나", "가 \u0301나"):
                with self.subTest(field=name, bad=bad):
                    self.assertEqual(refused(**{name: bad}).code, "DRAFT_OPTION_INVALID")

    def test_dangerous_markup_and_templates_are_refused(self):
        for name in TEXT_FIELDS:
            for bad in ("<script>alert(1)</script>", "<b>굵게</b>", "<img src=x onerror=1>", "{% include x %}", "{{ secret }}", "javascript:alert(1)", "onclick=run()", "<!-- 주석 -->"):
                with self.subTest(field=name, bad=bad):
                    error = refused(**{name: bad})
                    self.assertEqual(error.code, "DRAFT_OPTION_INVALID")
                    self.assertEqual(error.slots["항목"], do.LABELS[name])

    def test_ordinary_angle_brackets_and_colons_pass(self):
        self.assertEqual(DraftOptions(message="Map<String, List<Integer>> 같은 글자 3 < 5").message, "Map<String, List<Integer>> 같은 글자 3 < 5")
        self.assertEqual(DraftOptions(opinion="JavaScript: 비동기 처리").opinion, "JavaScript: 비동기 처리")

    def test_promises_about_results_are_refused_but_negations_and_warnings_pass(self):
        for name in TEXT_FIELDS:
            for bad in ("상위노출 보장", "검색 1위 가능성", "수익 보장 방법", "노출 확률 높이기"):
                with self.subTest(field=name, bad=bad):
                    error = refused(**{name: bad})
                    self.assertEqual(error.code, "DRAFT_OPTION_INVALID")
                    self.assertIn("결과를 약속하는 표현", error.slots["이유"])
        for good in ("상위노출은 보장하지 않습니다", "상위노출 보장 업체 피하는 법", "순위는 보장할 수 없습니다"):
            with self.subTest(good=good):
                self.assertEqual(DraftOptions(message=good).message, good)

    def test_the_users_own_experience_claims_are_not_refused(self):
        said = "직접 사용해보니 편리했습니다. 지난주에 방문했고 구매했습니다."
        options = DraftOptions(experience=said, opinion="써 본 결과 만족스러웠습니다", message="수익을 냈습니다")
        self.assertEqual((options.experience, options.opinion, options.message), (said, "써 본 결과 만족스러웠습니다", "수익을 냈습니다"))


class ListFieldTest(unittest.TestCase):
    def test_a_single_string_counts_as_one_item_and_order_is_kept(self):
        self.assertEqual(DraftOptions(must_include="한 문장").must_include, ("한 문장",))
        self.assertEqual(DraftOptions(exclude="광고").exclude, ("광고",))
        self.assertEqual(DraftOptions(price_date="12,000원").price_date, ("12,000원",))
        self.assertEqual(DraftOptions(urls="https://example.com/a").urls, ("https://example.com/a",))
        self.assertEqual(DraftOptions(must_include=["셋", "하나", "둘"]).must_include, ("셋", "하나", "둘"))

    def test_blank_items_are_dropped_and_duplicates_keep_the_first(self):
        options = DraftOptions(must_include=["  가 나 ", "", "가나", "다"], exclude=["광고", " 광  고 ", "ＡＤ", "ad"], price_date=["", "1만원", "1만원"])
        self.assertEqual(options.must_include, ("가 나", "다"))
        self.assertEqual(options.exclude, ("광고", "ＡＤ"))
        self.assertEqual(options.price_date, ("1만원",))

    def test_count_limits_are_inclusive(self):
        for name, high in (("must_include", 10), ("exclude", 20), ("price_date", 10)):
            with self.subTest(field=name):
                self.assertEqual(len(getattr(DraftOptions(**{name: [f"항목 {index}" for index in range(high)]}), name)), high)
                error = refused(**{name: [f"항목 {index}" for index in range(high + 1)]})
                self.assertEqual(error.code, "DRAFT_OPTION_INVALID")
                self.assertIn(f"{high}개까지", error.slots["이유"])

    def test_item_length_limits_are_inclusive(self):
        for name, high in (("must_include", 200), ("exclude", 60), ("price_date", 100)):
            with self.subTest(field=name):
                self.assertEqual(len(getattr(DraftOptions(**{name: ["가" * high]}), name)[0]), high)
                self.assertEqual(refused(**{name: ["가" * (high + 1)]}).code, "DRAFT_OPTION_INVALID")

    def test_unordered_or_wrong_collections_are_refused(self):
        for name in ("must_include", "exclude", "price_date", "urls"):
            for value in ({"가", "나"}, {"가": 1}, 5, b"x", object(), iter(["가"])):
                with self.subTest(field=name, value=type(value).__name__):
                    self.assertEqual(refused(**{name: value}).code, "DRAFT_OPTION_INVALID")
            with self.subTest(field=name, item="not text"):
                self.assertEqual(refused(**{name: ["가", 3]}).code, "DRAFT_OPTION_INVALID")

    def test_list_items_get_the_same_content_checks(self):
        for name in ("must_include", "exclude", "price_date"):
            for bad in ("<script>", "상위노출 보장", "가\u3164나"):
                with self.subTest(field=name, bad=bad):
                    self.assertEqual(refused(**{name: ["정상", bad]}).code, "DRAFT_OPTION_INVALID")


class HugeInputTest(unittest.TestCase):
    def test_huge_text_values_are_refused_quickly_without_scanning_them_all(self):
        import time
        for name in TEXT_FIELDS:
            with self.subTest(field=name):
                started = time.perf_counter()
                error = refused(**{name: "가" * 500_000})
                self.assertEqual(error.code, "DRAFT_OPTION_INVALID")
                self.assertLess(time.perf_counter() - started, 1.0)
        started = time.perf_counter()
        refused(message=" " * 500_000 + "가" * 501)
        refused(message="\u200b" * 500_000 + "가" * 501)
        self.assertLess(time.perf_counter() - started, 2.0)

    def test_a_huge_list_is_refused_before_every_item_is_checked(self):
        import time
        started = time.perf_counter()
        for name in ("must_include", "exclude", "price_date", "urls"):
            with self.subTest(field=name):
                value = ["가"] * 50_000 if name != "urls" else ["https://example.com/a"] * 50_000
                error = refused(**{name: value})
                self.assertEqual(error.code, "DRAFT_OPTION_INVALID")
                self.assertIn("너무 많습니다", error.slots["이유"])
        self.assertLess(time.perf_counter() - started, 1.0)

    def test_the_raw_item_limit_counts_blank_and_repeated_items_and_is_inclusive(self):
        self.assertEqual(do.RAW_ITEMS, 100)
        self.assertEqual(DraftOptions(must_include=[""] * 100).must_include, ())
        self.assertEqual(DraftOptions(exclude=["광고"] * 100).exclude, ("광고",))
        self.assertEqual(refused(must_include=[""] * 101).code, "DRAFT_OPTION_INVALID")
        self.assertEqual(refused(urls=["https://example.com/a"] * 101).code, "DRAFT_OPTION_INVALID")


LONG = "abcdefghijklmnopqrstuvwxyz012345"                          # 32자 — 키 모양은 아니지만 비밀 인자의 값으로는 긴 값
LONG40 = LONG + "6789ABCD"                                          # 40자


class UrlTest(unittest.TestCase):
    GOOD = (
        "https://example.com", "https://example.com/", "https://www.example.co.kr/path/to/page?id=3&lang=ko#top", "HTTPS://Example.COM/Path", "https://sub.domain.example.org:8443/x",
        "https://blog.naver.com/someone/123456", "https://한글도메인.kr/경로", "https://xn--bj0bj3k7ky.example/", "https://a-b.example.com", "https://example.com/a(b)_c-d.html",
        "https://1.example.com/", "https://a.1.example.com/x", "https://example.com/?keyword=abc&page=2&sort=asc", "https://example.com/#section-2", "https://example.com/docs#install", "https://test.com/", "https://home.example.com/", "https://local.example.org/",
    )
    BAD = (
        'http://example.com', 'ftp://example.com/file', 'javascript:alert(1)',
        'JavaScript:alert(1)', 'data:text/html,<b>x</b>', 'file:///etc/passwd',
        '//example.com/x', 'example.com', 'www.example.com/a',
        'https://', 'https:///path', 'https://user:pass@example.com/',
        'https://user@example.com/', 'https://example.com:443@evil.example/', 'https://localhost/x',
        'https://intranet/x', 'https://127.0.0.1/x', 'https://192.168.0.1/',
        'https://10.0.0.5:8080/', 'https://[::1]/', 'https://example..com/',
        'https://.example.com/', 'https://example.com./', 'https://-bad.example.com/',
        'https://exa_mple.com/', 'https://example.com/a b', 'https://example.com/a\tb',
        'https://example.com/\u202e/x', 'https://example.com/"x"', 'https://example.com/<x>',
        "https://example.com/a'b", 'https://example.com/a\\b', 'https://example.com/{x}',
        'https://example.com:99999/x', 'https://example.com:abc/x', "https://example.com/" + "a" * 300,
        'https://example.com:0/x', 'https://example.com:65536/x', 'https://0x7f.0.0.1/',
        'https://0x7f000001.com./x', 'https://127.1/', 'https://example.123/',
        'https://app.internal/x', 'https://printer.local/', 'https://host.lan/',
        'https://LOCALHOST/x', 'https://api.localhost/x', 'https://nas.home/x',
        'https://wiki.corp/x', 'https://x.test/', 'https://x.onion/',
        'https://x.localdomain/',
        # 비밀 인자 이름이 맞고 값도 긴 것(16자 이상)은 거절한다 — 이름 낱말과 같거나 그 낱말로 끝나는 이름만
        "https://example.com/?token=" + LONG, "https://example.com/?access_token=" + LONG, "https://example.com/?api_key=" + LONG, "https://example.com/?apikey=" + LONG,
        "https://example.com/?Password=" + LONG, "https://example.com/?x=1&secret=" + LONG, "https://example.com/?secret_key=" + LONG, "https://example.com/?access_key=" + LONG,
        "https://example.com/?X-Amz-Signature=" + LONG, "https://example.com/?jwt=" + LONG, "https://example.com/?Authorization=" + LONG, "https://example.com/?auth_token=" + LONG,
        "https://example.com/?client.secret=" + LONG, "https://example.com/?private-key=" + LONG, "https://example.com/?X-Amz-Credential=" + LONG, "https://example.com/?key=" + LONG,
        "https://example.com/?sig=" + LONG, "https://example.com/?auth=" + LONG, "https://example.com/#access_token=" + LONG + "&token_type=bearer", "https://example.com/#token=" + LONG,
        "https://example.com/?page=1#id_token=" + LONG, "https://example.com/#/cb?token=" + LONG, "https://example.com/a;token=" + LONG, "https://example.com/?token=%41%42%43%44%45%46%47%48%49%4a%4b%4c%4d%4e%4f%50",
    )
    LONG_SHORT_OK = ('https://example.com/?token=abc123', 'https://example.com/?access_token=abc', 'https://example.com/?api_key=1', 'https://example.com/?apikey=1', 'https://example.com/?Password=1', 'https://example.com/?x=1&secret=2', 'https://example.com/?session-id=3', 'https://example.com/?code=xyz', 'https://example.com/?token', 'https://example.com/?secret=', 'https://example.com/?secret_key=1', 'https://example.com/?access_key=1', 'https://example.com/?X-Amz-Signature=abc', 'https://example.com/?jwt=abc', 'https://example.com/?Authorization=abc', 'https://example.com/?auth_token=abc', 'https://example.com/?client.secret=1', 'https://example.com/?private-key=1', 'https://example.com/?X-Amz-Credential=1', 'https://example.com/?otp=123456', 'https://example.com/#access_token=abc&token_type=bearer', 'https://example.com/#token=abc', 'https://example.com/?page=1#id_token=abc', 'https://example.com/#/cb?code=abc')

    def test_good_addresses_are_kept_as_typed(self):
        for url in self.GOOD:
            with self.subTest(url=url):
                self.assertEqual(DraftOptions(urls=[url]).urls, (url,))

    def test_bad_addresses_are_refused_with_the_field_name_and_a_reason(self):
        for url in self.BAD:
            with self.subTest(url=url):
                error = refused(urls=[url])
                self.assertEqual(error.code, "DRAFT_OPTION_INVALID")
                self.assertEqual(error.slots["항목"], "참고 URL")
                self.assertTrue(error.slots["이유"])

    def test_a_non_text_address_or_length_is_refused_with_the_field_name(self):
        for work in (lambda: parse_length(5), lambda: DraftOptions(urls=[5]), lambda: DraftOptions(urls=[None]), lambda: DraftOptions(length=5)):
            with self.assertRaises(AppError) as caught:
                work()
            self.assertEqual(caught.exception.code, "DRAFT_OPTION_INVALID")
            self.assertTrue(caught.exception.slots["이유"])
        self.assertEqual(DraftOptions(urls=[""]).urls, ())

    def test_the_reason_says_what_is_wrong(self):
        control = chr(0x200B)
        bidi = chr(0x202E)
        cases = (("https://user:pass@example.com/", "로그인 정보"), ("https://exa" + control + "mple.com/", "제어 문자"), ("https://example.com/x" + bidi, "제어 문자"), ("https://example.com:0/x", "포트"),
                 ("https://example.com/a b", "공백"), ("ftp://example.com/", "https://"), ("https://localhost/x", "공개 사이트"), ("https://127.0.0.1/", "IP 주소"), ("https://app.internal/", "내부망"),
                 ("https://example.com/?token=" + LONG, "토큰"), ("https://example.com/#access_token=" + LONG, "토큰"), ("https://example.com/?token=" + LONG, "? 뒤를 빼고"))
        for url, word in cases:
            with self.subTest(url=url):
                self.assertIn(word, refused(urls=[url]).slots["이유"])

    def test_common_query_names_and_short_secret_values_pass(self):
        for url in ("https://example.com/?code=200", "https://example.com/?sessions=2", "https://example.com/?tokenizer=on", "https://example.com/?ticket=abc", "https://example.com/?token=12345",
                    "https://example.com/?password=", "https://example.com/?key=home", "https://example.com/?sig=abc", "https://example.com/?secretary=kim", "https://example.com/?authors=lee&tokens=a",
                    "https://example.com/a;v=2", "https://example.com/?country_code=KR", "https://example.com/?sid=12", "https://example.com/?auth=true", "https://example.com/?utm_source=news&utm_medium=email",
                    "https://example.com/?token=abcdefg", "https://example.com/?token=12345678901234567890", "https://example.com/?access_token=abc12345"):
            with self.subTest(url=url):
                self.assertEqual(DraftOptions(urls=[url]).urls, (url,))
        for url in self.LONG_SHORT_OK:
            with self.subTest(url=url):
                self.assertEqual(DraftOptions(urls=[url]).urls, (url,))

    def test_the_value_rule_has_exact_edges(self):
        for length, refused_it in ((0, False), (7, False), (8, False), (15, False), (16, True), (40, True)):
            url = "https://example.com/?token=" + "a" * length
            with self.subTest(length=length):
                if refused_it:
                    self.assertEqual(refused(urls=[url]).code, "DRAFT_OPTION_INVALID")
                else:
                    self.assertEqual(DraftOptions(urls=[url]).urls, (url,))
        self.assertEqual(DraftOptions(urls=["https://example.com/?token=" + "1" * 30]).urls, ("https://example.com/?token=" + "1" * 30,), "숫자뿐인 값은 상태 번호처럼 쓰인다")

    def test_the_name_rule_contains_a_secret_word_or_equals_an_ambiguous_one(self):
        for name in ("token", "access_token", "Access-Token", "refresh.token", "apikey", "api_key", "x-api-key", "secret", "client_secret", "password", "passwd", "pwd", "signature", "X-Amz-Signature", "authorization", "bearer", "jwt",
                     "credential", "X-Amz-Credential", "access_key", "private-key", "token_value", "token2", "token[]", "access_token_v2", "secret_value", "password_hash", "tokenizer", "tokens", "secretary", "authToken",
                     "sessionid", "jsessionid", "PHPSESSID", "ASP.NET_SessionId", "sessid"):
            with self.subTest(name=name):
                self.assertTrue(do._secret_name(name), name)
        for name in ("sig", "key", "auth", "pass", "otp", "sign", "sid", "ticket", "code", "session", "Sid", "CODE", "Session"):
            with self.subTest(name=name):
                self.assertTrue(do._secret_name(name), name)
        for name in ("sessions", "sid1", "tickets", "country_code", "codes", "session_name", "keyword", "keys", "monkey", "authors", "authkey", "pass-through", "passport", "bypass", "signup", "design", "otp2", "page", ""):
            with self.subTest(name=name):
                self.assertFalse(do._secret_name(name), name)

    def test_an_ambiguous_word_counts_only_as_the_whole_name(self):
        for name in ("sid", "ticket", "code", "session", "key", "sig", "auth", "pass", "otp", "sign"):
            with self.subTest(name=name):
                self.assertEqual(refused(urls=["https://example.com/?" + name + "=" + LONG40]).code, "DRAFT_OPTION_INVALID")
        for name in ("sid1", "tickets", "country_code", "codes", "sessions", "session_name", "keyword", "keys", "monkey", "authors", "authkey", "passport", "bypass", "signup", "design", "otp2"):
            url = "https://example.com/?" + name + "=" + LONG40
            with self.subTest(name=name):
                self.assertEqual(DraftOptions(urls=[url]).urls, (url,))

    def test_a_secret_word_inside_the_name_counts_with_a_long_value_but_not_a_short_one(self):
        for name in ("token_value", "token2", "tokenizer", "secretary", "password_hash", "secret_value", "access_token_v2", "token[]"):
            with self.subTest(name=name):
                self.assertEqual(refused(urls=["https://example.com/?" + name + "=" + LONG40]).code, "DRAFT_OPTION_INVALID")
                short = "https://example.com/?" + name + "=on"
                self.assertEqual(DraftOptions(urls=[short]).urls, (short,))

    LEAKING_NAMES = ("session", "sessionid", "sid", "code", "ticket", "token_value", "token2", "token[]", "access_token_v2", "secret_value", "password_hash", "jsessionid", "PHPSESSID")

    def test_every_shape_that_leaked_in_the_second_review_is_refused(self):
        count = 0
        for name in self.LEAKING_NAMES:
            for template in ("https://example.com/p?{n}={v}", "https://example.com/cb#{n}={v}"):
                url = template.format(n=name, v=LONG40)
                count += 1
                with self.subTest(url=url[:48]):
                    self.assertIn("? 뒤를 빼고", refused(urls=[url]).slots["이유"])
        for url in ("https://example.com/p?token%3D" + LONG40, "https://example.com/a/token%3D" + LONG40, "https://example.com/p?token%253D" + LONG40, "https://example.com/p?x=1%26token%3D" + LONG40,
                    "https://example.com/p?next=%2Fcb%3Ftoken%3D" + LONG40, "https://example.com/p?next=%2Fcb%3Fsid%3D" + LONG40, "https://example.com/cb%23access_token%3D" + LONG40):
            count += 1
            with self.subTest(url=url[:48]):
                self.assertIn("? 뒤를 빼고", refused(urls=[url]).slots["이유"])
        self.assertEqual(count, 33)

    def test_the_refusal_for_a_percent_written_parameter_does_not_show_it(self):
        error = refused(urls=["https://example.com/p?token%3D" + LONG40])
        shown = " ".join([str(error.rendered().message), str(error.detail), repr(error.slots)])
        self.assertNotIn(LONG40[:12], shown)
        self.assertNotIn("token", shown.casefold())

    NORMAL_ADDRESSES = (
        'https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=10s', 'https://search.naver.com/search.naver?query=보일러+점검&where=blog', 'https://example.com/page?id=3&lang=ko',
        'https://blog.naver.com/PostView.naver?blogId=abc&logNo=223000000000', 'https://www.google.com/search?q=boiler&hl=ko', 'https://ko.wikipedia.org/wiki/보일러', 'https://github.com/user/repo/issues/12',
        'https://news.naver.com/main/read.naver?oid=001&aid=0012345678&sid1=100', 'https://www.coupang.com/vp/products/123?itemId=456&vendorItemId=789', 'https://example.com/docs#section-2', 'https://example.com/app#/page?x=1',
        'https://example.com/a?utm_source=news&utm_medium=email', 'https://example.com/authors/kim', 'https://example.com/token-economy-guide', 'https://example.com/session-notes', 'https://example.com/secret-garden',
        'https://example.com/?code=200', 'https://example.com/search?country_code=KR', 'https://example.com/?sessions=2', 'https://example.com/?tokenizer=bert', 'https://example.com/?ticket=A123', 'https://example.com/p?sid=12',
        'https://example.com/?auth=true', 'https://example.com/?otp=off', 'https://example.com/p?key=value', 'https://example.com/report?year=2026&sig=3', 'https://example.com/?keyword=보일러', 'https://example.com/?apikey_guide=1',
        'https://example.com/p?page=2&sort=new', 'https://example.com/?ref=main&lang=ko', 'https://docs.google.com/document/d/1AbCdEfGhIjKlMnOpQrStUvWxYz0123456789abcdefg/edit',
        'https://drive.google.com/file/d/1a2B3c4D5e6F7g8H9i0JkLmNoPqRsTuVw/view?usp=sharing', 'https://www.amazon.com/dp/B08N5WRWNW?ref=nav_logo&th=1&psc=1',
        'https://www.coupang.com/vp/products/123?itemId=456&vendorItemId=789&q=%EB%B3%B4%EC%9D%BC%EB%9F%AC&itemsCount=36&searchId=0fb5b3e1c8d94a1d9a31&rank=1',
        'https://blog.naver.com/PostView.naver?blogId=abc123&logNo=223000000000&redirect=Dlog&widgetTypeCall=true&directAccess=false', 'https://abc.tistory.com/123',
        'https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PLrAXtmErZgOeiKm4sgNOknGvNjby9efdf&index=2', 'https://ko.wikipedia.org/wiki/%EB%B3%B4%EC%9D%BC%EB%9F%AC_(%EB%82%9C%EB%B0%A9)',
        'https://github.com/user/repo/commit/0123456789abcdef0123456789abcdef01234567', 'https://github.com/user/repo/blob/main/docs/README.md#L10-L20',
        'https://stackoverflow.com/questions/12345678/how-to-use-a-secret-token-in-python', 'https://example.com/blog/2026/11/03/how-to-reset-your-password-safely', 'https://example.com/guide/api-key-management-best-practices',
        'https://example.com/search?q=api+key+rotation&page=2', 'https://example.com/products?category=boiler&sort=price_asc&min_price=100000&max_price=500000',
        'https://example.com/news/article?id=20261103000123&section=economy&ref=mainpage', 'https://news.naver.com/main/read.naver?mode=LSD&mid=shm&sid1=105&oid=092&aid=0002345678',
        'https://search.daum.net/search?w=blog&q=%EB%B3%B4%EC%9D%BC%EB%9F%AC+%EC%A0%90%EA%B2%80&DA=PGD', 'https://map.naver.com/p/search/%EC%84%B1%EC%88%98%EB%8F%99%20%EC%B9%B4%ED%8E%98',
        'https://www.instagram.com/p/CxYz123AbCd/?igsh=MWQ1ZGUxMzBkMg==', 'https://twitter.com/user/status/1234567890123456789?s=20&t=AbCdEfGhIjKlMn', 'https://www.notion.so/My-Page-0123456789abcdef0123456789abcdef',
        'https://medium.com/@someone/post-title-1a2b3c4d5e6f', 'https://example.com/download?file=report-2026.pdf&version=3&lang=ko', 'https://example.com/events?date=2026-11-03&time=10:00&place=seoul',
        'https://example.com/price?currency=KRW&amount=1200000&tax=included', 'https://example.com/p/1?authors=kim,lee&tokens=a', 'https://example.com/p?secretary=kim&passwords=on',
        'https://example.com/p?next=%2Fdashboard%3Ftab%3D2&lang=ko', 'https://example.com/shop?brand=lg&model=ABCD-1234-XYZ-5678-QWER&color=white', 'https://example.com/a?key_word=boiler&keys=2',
        'https://example.com/?cid=3a7f9c2e1b4d6f8a0c2e4a6b8d0f1a3c', 'https://example.com/?uid=8f14e45fceea167a5a36dedd4bea2543', 'https://example.com/?trackingId=abcdefghijklmnopqrstuvwx',
        'https://example.com/?shareId=AbCdEfGhIjKlMnOpQrStUvWxYz', 'https://example.com/?sessionToken=short', 'https://example.com/p?pass=1&sign=ok', 'https://example.com/p?auth=oauth2&scope=read',
        'https://example.com/?authKey=abc', 'https://www.google.com/maps/place/Seoul/@37.5665,126.9780,12z', 'https://example.com/#/dashboard/overview?tab=3',
        'https://example.com/page?utm_source=newsletter&utm_campaign=2026-11&utm_content=btn1',
    )

    def test_seventy_two_ordinary_addresses_are_never_refused(self):
        self.assertEqual(len(self.NORMAL_ADDRESSES), 72)
        self.assertEqual(len(set(self.NORMAL_ADDRESSES)), 72)
        for url in self.NORMAL_ADDRESSES:
            with self.subTest(url=url):
                self.assertEqual(DraftOptions(urls=[url]).urls, (url,))

    def test_the_forms_are_the_text_and_at_most_two_decodings(self):
        self.assertEqual(do._forms("https://a.example/x"), ["https://a.example/x"])
        self.assertEqual(do._forms("a%3Db"), ["a%3Db", "a=b"])
        self.assertEqual(do._forms("a%253Db"), ["a%253Db", "a%3Db", "a=b"])
        self.assertEqual(len(do._forms("a%25253Db")), 3)

    def test_a_long_value_holding_an_encoded_separator_is_one_value_in_the_raw_text(self):
        self.assertEqual(refused(urls=["https://example.com/?token=aaaa%26" + "b" * 20]).code, "DRAFT_OPTION_INVALID")
        self.assertEqual(refused(urls=["https://example.com/?sid=aaaa%23" + "b" * 20]).code, "DRAFT_OPTION_INVALID")
        self.assertEqual(DraftOptions(urls=["https://example.com/?token=aaaa%26b"]).urls, ("https://example.com/?token=aaaa%26b",))

    def test_a_percent_written_name_or_value_is_read_the_same(self):
        self.assertEqual(refused(urls=["https://example.com/?access%5Ftoken=" + LONG]).code, "DRAFT_OPTION_INVALID")
        self.assertEqual(refused(urls=["https://example.com/?token=" + "%41" * 20]).code, "DRAFT_OPTION_INVALID")
        self.assertEqual(DraftOptions(urls=["https://example.com/?tok%65nizer=on"]).urls, ("https://example.com/?tok%65nizer=on",))
        self.assertEqual(refused(urls=["https://example.com/?tok%65n=" + LONG]).code, "DRAFT_OPTION_INVALID")                          # %65 = e — 이름도 풀어서 본다
        self.assertEqual(DraftOptions(urls=["https://example.com/?token=" + "%41" * 6]).urls, ("https://example.com/?token=" + "%41" * 6,), "풀면 6글자라 짧은 값이다")

    def test_the_refusal_never_names_the_parameter(self):
        for name in ("mySecretProjectCodeToken", "customer-7731-private-apikey", "internal.build.signature"):
            error = refused(urls=["https://example.com/?" + name + "=" + LONG])
            shown = " ".join([str(error.rendered().message), str(error.detail), repr(error.slots)])
            with self.subTest(name=name):
                self.assertNotIn(name[:12], shown)
                self.assertNotIn(LONG[:12], shown)

    def test_a_name_with_an_equals_sign_inside_the_path_is_read_too(self):
        self.assertEqual(refused(urls=["https://example.com/a/key=" + LONG]).code, "DRAFT_OPTION_INVALID")
        self.assertEqual(refused(urls=["https://example.com/a;key=" + LONG]).code, "DRAFT_OPTION_INVALID")
        self.assertEqual(DraftOptions(urls=["https://example.com/a/key=home"]).urls, ("https://example.com/a/key=home",))

    def test_a_key_shaped_text_in_the_path_or_percent_written_is_refused(self):
        for url in ("https://example.com/" + KEYS["ghp"], "https://example.com/a/" + KEYS["AKIA"] + "/b", "https://example.com/Bearer%20" + KEYS["bearer-body"], "https://example.com/가" + KEYS["sk"] + "나"):
            with self.subTest(url=url[:40]):
                error = refused(urls=[url])
                self.assertIn("키·토큰처럼", error.slots["이유"])
                self.assertIn("빼고", error.slots["이유"])

    def test_the_text_policy_refuses_name_value_shapes_and_says_how_to_fix_it(self):
        for text in ("password: required", "secret: 비공개메뉴 안내", "apikey = 발급받은값 입력"):
            with self.subTest(text=text):
                reason = refused(message=text).slots["이유"]
                self.assertIn("‘이름: 값’ 꼴", reason)
                self.assertIn("문장으로 바꿔 써 주세요", reason)
        for text in ("비밀번호 password 를 바꾸는 방법", "token 이란 무엇인가", "tokenizer 사용 방법", "API key 를 발급받는 방법", "task-force 운영 방법", "AKIAN 브랜드 소개", "주문번호 ORD20261103ABCDEF1234 조회"):
            with self.subTest(text=text):
                self.assertEqual(DraftOptions(message=text).message, text)

    def test_the_longest_allowed_address_passes(self):
        url = "https://example.com/" + "a" * (300 - len("https://example.com/"))
        self.assertEqual(len(url), 300)
        self.assertEqual(refused(urls=[url + "a"]).code, "DRAFT_OPTION_INVALID")
        self.assertEqual(DraftOptions(urls=[url]).urls, (url,))

    def test_at_most_ten_addresses_and_duplicates_collapse(self):
        urls = [f"https://example.com/{index}" for index in range(10)]
        self.assertEqual(len(DraftOptions(urls=urls).urls), 10)
        self.assertEqual(refused(urls=urls + ["https://example.com/extra"]).code, "DRAFT_OPTION_INVALID")
        self.assertEqual(DraftOptions(urls=["https://Example.com/A", "https://example.com/A", "https://EXAMPLE.COM/A"]).urls, ("https://Example.com/A",))      # 사이트 이름은 대소문자를 무시해 하나로 합친다
        self.assertEqual(DraftOptions(urls=["https://Example.com/A", "https://example.com/a"]).urls, ("https://Example.com/A", "https://example.com/a"))     # 경로·인자는 대소문자를 구분한다
        self.assertEqual(len(DraftOptions(urls=["https://example.com/?q=A", "https://example.com/?q=a", "https://example.com/#A", "https://example.com/#a"]).urls), 4)

    def test_urls_are_never_opened_or_fetched(self):
        with mock.patch.object(socket, "socket", side_effect=AssertionError("네트워크를 쓰면 안 된다")), mock.patch.object(socket, "getaddrinfo", side_effect=AssertionError("이름을 찾으면 안 된다")):
            options = DraftOptions(urls=["https://example.com/a", "https://blog.naver.com/x/1"])
            self.assertEqual(len(options.urls), 2)
            self.assertEqual(DraftOptions.from_dict(options.to_dict()), options)

    def test_a_bad_address_in_a_list_refuses_the_whole_input(self):
        self.assertEqual(refused(urls=["https://example.com/a", "http://example.com/b"]).code, "DRAFT_OPTION_INVALID")


class LengthTest(unittest.TestCase):
    ACCEPTED = (
        ("1500-2000", (1500, 2000)), ("1500~2000", (1500, 2000)), ("1500 - 2000", (1500, 2000)), ("1,500~2,000자", (1500, 2000)), ("1500자-2000자", (1500, 2000)), ("１５００〜２０００", (1500, 2000)),
        ("1500–2000", (1500, 2000)), ("2500+", (2500, None)), ("2,500+", (2500, None)), ("2500이상", (2500, None)), ("2500자 이상", (2500, None)), ("2500~", (2500, None)), ("2500-", (2500, None)),
        ("200-200", (200, 200)), ("200", None), ("100000+", (100000, None)), ("200-100000", (200, 100000)),
    )
    REFUSED = ("", "abc", "2000", "2000자", "-2000", "2000-1500", "199-500", "199+", "100001+", "200-100001", "1500--2000", "1500~2000~2500", "약 2000자", "1500-2000-", "2500++", "0+",
               "12+", "1234567+", "1e3-2e3", "1500 2000", "1500,2000", "이상2500", "２５００＋\u3000이상")

    def test_accepted_shapes(self):
        for text, expected in self.ACCEPTED:
            if expected is None:
                continue
            with self.subTest(text=text):
                wish = parse_length(text)
                self.assertEqual((wish.low, wish.high), expected)
                self.assertEqual(DraftOptions(length=text).length, wish)

    def test_refused_shapes(self):
        for text in self.REFUSED:
            if text == "":
                continue
            with self.subTest(text=text):
                with self.assertRaises(AppError) as caught:
                    parse_length(text)
                self.assertEqual(caught.exception.code, "DRAFT_OPTION_INVALID")
                self.assertEqual(caught.exception.slots["항목"], "원하는 글 길이")

    def test_bounds_are_inclusive(self):
        self.assertEqual(parse_length("200-200").low, 200)
        self.assertEqual(parse_length("100000+").low, 100000)
        self.assertEqual(parse_length("200-100000").high, 100000)
        for text in ("199-300", "100001+", "200-100001", "300-299"):
            with self.subTest(text=text), self.assertRaises(AppError):
                parse_length(text)

    def test_the_objects_text_and_korean_forms(self):
        self.assertEqual(LengthWish(1500, 2000).text(), "1500-2000")
        self.assertEqual(LengthWish(2500).text(), "2500+")
        self.assertEqual(LengthWish(1500, 2000).korean(), "1,500~2,000자")
        self.assertEqual(LengthWish(2500).korean(), "2,500자 이상")
        self.assertEqual(LengthWish(2500).to_range(), (2500, None))
        for wish in (LengthWish(200, 200), LengthWish(1500, 2000), LengthWish(2500)):
            self.assertEqual(parse_length(wish.text()), wish)

    def test_invalid_objects_are_refused(self):
        for args in ((199,), (100001,), (300, 299), (300, 100001), ("1500",), (True,), (1500.0,), (1500, "2000"), (1500, True)):
            with self.subTest(args=args), self.assertRaises(AppError):
                LengthWish(*args)
        for value in (2500, 1500.5, ["1500-2000"], (1500, 2000), True):
            with self.subTest(value=value):
                self.assertEqual(refused(length=value).code, "DRAFT_OPTION_INVALID")

    def test_a_wish_object_is_accepted_as_is(self):
        wish = LengthWish(1500, 2000)
        self.assertIs(DraftOptions(length=wish).length, wish)


class JsonTest(unittest.TestCase):
    RICH = dict(message="전하고 싶은 말", experience="직접 써 본 경험입니다.", opinion="개인 의견입니다", must_include=("꼭 넣을 문장", "둘째 문장"), exclude=("광고", "가격"), audience="사회 초년생",
                length="2500+", title_direction="질문형으로", urls=("https://example.com/a", "https://blog.naver.com/x/1"), price_date=("12,000원(2026-11-01 기준)",), conclusion="결론은 비교 후 선택입니다")

    def test_roundtrip_keeps_every_field(self):
        options = DraftOptions(**self.RICH)
        for restored in (DraftOptions.from_dict(options.to_dict()), DraftOptions.from_json(options.to_json())):
            self.assertEqual(restored, options)
        self.assertEqual(options.to_dict()["length"], "2500+")
        self.assertEqual(options.to_dict()["schema"], 1)

    def test_empty_options_roundtrip_to_empty_values(self):
        data = DraftOptions().to_dict()
        self.assertEqual(data, {"schema": 1, "message": "", "experience": "", "opinion": "", "must_include": [], "exclude": [], "audience": "", "length": None, "title_direction": "", "urls": [], "price_date": [],
                                "conclusion": ""})
        self.assertEqual(DraftOptions.from_dict(data), DraftOptions())
        self.assertEqual(DraftOptions.from_dict({}), DraftOptions())
        self.assertEqual(DraftOptions.from_dict({"schema": 1}), DraftOptions())

    def test_the_json_text_is_stable(self):
        options = DraftOptions(**self.RICH)
        self.assertEqual(options.to_json(), options.to_json())
        self.assertEqual(options.to_json(), DraftOptions.from_json(options.to_json()).to_json())
        self.assertIn("직접 써 본 경험입니다.", options.to_json())                      # 한글을 이스케이프하지 않는다

    def test_unknown_keys_and_wrong_shapes_are_refused(self):
        good = DraftOptions(**self.RICH).to_dict()
        bad_inputs = [{**good, "extra": 1}, {**good, "schema": 2}, {**good, "schema": "1"}, {**good, "schema": True}, {"Message": "x"}, {"message": 5}, {"must_include": 5},
                      {"length": 2500}, {"urls": ["http://example.com"]}, {"exclude": {"가"}}, [], "문자열", None, 5, {5: "x"}, {"messages": "x"}]
        for data in bad_inputs:
            with self.subTest(data=str(data)[:60]):
                with self.assertRaises(AppError) as caught:
                    DraftOptions.from_dict(data)
                self.assertEqual(caught.exception.code, "DRAFT_OPTION_INVALID")

    def test_a_key_that_appears_twice_is_refused_instead_of_keeping_the_last(self):
        for text in ('{"message": "가", "message": "나"}', '{"exclude": ["가"], "exclude": []}', '{"schema": 1, "schema": 1}'):
            with self.subTest(text=text), self.assertRaises(AppError) as caught:
                DraftOptions.from_json(text)
            self.assertEqual(caught.exception.code, "DRAFT_OPTION_INVALID")
            self.assertIn("같은 키", caught.exception.slots["이유"])

    def test_deeply_nested_json_is_a_clean_error_not_a_crash(self):
        for text in ("[" * 200_000, "[" * 200_000 + "]" * 200_000, '{"message":' * 100_000):
            with self.subTest(size=len(text)), self.assertRaises(AppError) as caught:
                DraftOptions.from_json(text)
            self.assertEqual(caught.exception.code, "DRAFT_OPTION_INVALID")

    def test_a_single_string_in_a_list_field_is_accepted_from_json_too(self):
        self.assertEqual(DraftOptions.from_dict({"must_include": "한 문장"}).must_include, ("한 문장",))

    def test_from_json_refuses_text_that_is_not_json(self):
        for text in ("", "{", "not json", "[1,2]", "5", "null", '"x"', '{"message": }', None, 5):
            with self.subTest(text=text):
                with self.assertRaises(AppError) as caught:
                    DraftOptions.from_json(text)
                self.assertEqual(caught.exception.code, "DRAFT_OPTION_INVALID")

    def test_from_dict_applies_every_content_check(self):
        for data in ({"message": "<script>"}, {"opinion": "상위노출 보장"}, {"audience": "가" * 101}, {"urls": ["javascript:alert(1)"]}):
            with self.subTest(data=data), self.assertRaises(AppError):
                DraftOptions.from_dict(data)


class SquashTest(unittest.TestCase):
    def test_squash_ignores_spaces_case_and_width(self):
        self.assertEqual(do.squash("가상 자산"), do.squash("가상자산"))
        self.assertEqual(do.squash("ＡＩ 도구"), do.squash("ai도구"))
        self.assertEqual(do.squash(" \t\n"), "")
        self.assertNotEqual(do.squash("가나"), do.squash("나가"))


class ErrorShapeTest(unittest.TestCase):
    def test_the_error_message_names_the_field_and_the_reason(self):
        error = refused(urls=["http://example.com"])
        shown = error.rendered()
        self.assertEqual(shown.code, "DRAFT_OPTION_INVALID")
        self.assertIn("참고 URL", shown.message)
        self.assertIn("https://", shown.message)
        self.assertEqual(shown.retry_kind, "after_user")

    def test_no_value_is_echoed_into_secrets(self):
        error = refused(urls=["https://user:hunter2@example.com/"])
        self.assertNotIn("hunter2", error.rendered().message)
        self.assertNotIn("hunter2", str(error.detail))


ALNUM = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
UPPER_DIGITS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"


def _body(count, alphabet=ALNUM, step=7):
    return "".join(alphabet[(index * step + 3) % len(alphabet)] for index in range(count))


KEYS = {                                                      # 키 모양의 가짜 값 14종 — 저장소에는 키 모양 글이 통째로 있으면 안 되므로 조각을 이어서 만든다
    "AIza": "AI" + "za" + _body(35, ALNUM + "_-"), "AQ.": "AQ" + "." + _body(44, ALNUM + "_-"), "GOCSPX": "GOC" + "SPX-" + _body(24, ALNUM + "_-"), "ghp": "gh" + "p_" + _body(36),
    "github_pat": "github" + "_pat_" + _body(50), "xoxb": "xo" + "xb-" + "1234567890-" + _body(20), "AKIA": "AK" + "IA" + _body(16, UPPER_DIGITS), "sk": "s" + "k-" + _body(44),
    "telegram": "123456789" + ":" + _body(35, ALNUM + "_-"), "jwt": "ey" + "J" + _body(20) + "." + _body(20) + "." + _body(20), "bearer": "Bear" + "er " + _body(30), "bearer-body": _body(30),
    "password=": "pass" + "word=" + _body(14), "token:": "tok" + "en: " + _body(14), "npm": "np" + "m_" + _body(36),
}
CONTEXTS = {"단독": "{k}", "공백 사이": "키는 {k} 입니다", "뒤 조사": "{k}를 쓰세요", "앞 한글": "키{k}", "한글 사이": "키는{k}입니다", "괄호": "({k})", "따옴표": '"{k}"', "쉼표": "{k},끝", "마침표": "{k}.",
            "줄바꿈": "앞 줄" + chr(10) + "{k}" + chr(10) + "뒷 줄", "대괄호": "[{k}]", "작은따옴표": "'{k}'"}
MATRIX_FIELDS = ("message", "experience", "opinion", "audience", "title_direction", "conclusion", "must_include", "exclude", "price_date")


def fragments(secret, size=10):
    body = secret.replace("Bearer ", "").replace("password=", "").replace("token: ", "")
    return {body[index:index + size] for index in range(0, max(len(body) - size + 1, 1), 3)} | {body[:12], body[-12:]}


SECRETS = (                                                   # 키 모양의 가짜 값 — 저장소에는 키 모양 글이 통째로 있으면 안 되므로 조각을 이어서 만든다
    "AI" + "zaSyA1234567890abcdefghijklmnopqrstuvw",
    "gh" + "p_1234567890abcdefghijklmnopqrstuvwxyz",
    "s" + "k-abcdefghijklmnopqrstuvwxyz1234567890",
    "AK" + "IAIOSFODNN7EXAMPLE",
    "xo" + "xb-1234567890-abcdefghijklmnop",
)


def leaks(error, secret):
    """오류의 문구·세부·칸 값·표현 어디에든 비밀 모양의 앞이나 뒤 12자(마스크가 못 알아보는 조각)가 있는가."""
    shown = error.rendered()
    bag = " ".join([str(shown.message), str(getattr(shown, "action", "")), str(error.detail), repr(error.slots), repr(error), str(error)])
    return secret[:12] in bag or secret[-12:] in bag


class KeyNextToHangulAndPunctuationTest(unittest.TestCase):
    """한글·괄호·따옴표·쉼표·마침표·줄바꿈에 바로 붙은 키(검증자 조합 14종 × 12맥락 × 9칸)는 모두 거절되고, 거절 오류 어디에도 키의 앞뒤·가운데 조각이 나오지 않는다."""

    def kinds(self):
        return {label: secret for label, secret in KEYS.items() if label != "bearer-body"}

    def test_every_combination_is_refused_without_echoing_any_fragment(self):
        count = 0
        for label, secret in self.kinds().items():
            for context_name, context in CONTEXTS.items():
                for field in MATRIX_FIELDS:
                    text = context.replace("{k}", secret)
                    value = (text,) if field in ("must_include", "exclude", "price_date") else text
                    count += 1
                    with self.subTest(kind=label, context=context_name, field=field):
                        with self.assertRaises(AppError) as caught:
                            DraftOptions(**{field: value})
                        error = caught.exception
                        self.assertEqual(error.code, "DRAFT_OPTION_INVALID")
                        shown = " ".join([str(error.rendered().message), str(error.detail), repr(error.slots)])
                        self.assertFalse([piece for piece in fragments(secret) if piece in shown], "키 조각이 오류에 나왔다")
        self.assertEqual(count, 14 * 12 * 9)

    def test_the_same_keys_in_addresses_are_refused_or_never_printable(self):
        for label, secret in self.kinds().items():
            for template in ("https://example.com/{k}", "https://example.com/a?x={k}", "https://example.com/a#{k}", "https://example.com/가{k}나", "https://example.com/a?{k}"):
                url = template.replace("{k}", secret.replace(" ", "%20"))
                with self.subTest(kind=label, template=template):
                    try:
                        DraftOptions(urls=(url,))
                    except AppError as error:
                        shown = " ".join([str(error.rendered().message), str(error.detail), repr(error.slots)])
                        self.assertFalse([piece for piece in fragments(secret) if piece in shown])
                    else:
                        self.assertIn(label, ("password=", "token:"), "키 모양이 주소에 있는데 받았다")      # 짧은 값의 `이름=값` 꼴만 받는다(출력은 가려진다)


class SecretShapedInputIsNeverEchoedTest(unittest.TestCase):
    """비밀 모양의 글을 틀린 칸에 넣어도 오류의 어느 글에도(앞 30자 같은 조각이라도) 나오지 않는다 — 마스크는 전체 모양만 알아보므로 조각은 마스크가 못 막는다."""

    def check(self, secret, make):
        with self.assertRaises(AppError) as caught:
            make()
        self.assertFalse(leaks(caught.exception, secret), (secret[:6], repr(caught.exception.detail), caught.exception.slots))
        return caught.exception

    def test_a_wrong_length_never_shows_the_text_it_got(self):
        for secret in SECRETS:
            for wrapped in (secret, "약 " + secret + " 자", secret + "-" + secret, secret + "+"):
                with self.subTest(text=wrapped[:12]):
                    self.check(secret, lambda: parse_length(wrapped))
                    self.check(secret, lambda: DraftOptions(length=wrapped))

    def test_a_wrong_address_never_shows_any_part_of_the_address(self):
        for secret in SECRETS:
            shapes = (secret, secret + ":path", "ftp://" + secret, "https://example.com/?token=" + secret, "https://example.com/#access_token=" + secret, "https://user:" + secret + "@example.com/",
                      "https://" + secret + "/x", "https://example.com:" + secret + "/", "http://example.com/" + secret, "https://example.com/?" + secret + "=1&secret=" + secret, "https://example.com/?token_" + secret + "=1")
            for shape in shapes:
                with self.subTest(url=shape[:20]):
                    self.check(secret, lambda: DraftOptions(urls=[shape]))

    def test_a_secret_shaped_value_is_refused_as_such_in_every_text_field(self):
        for secret in SECRETS:
            with self.subTest(secret=secret[:6]):
                for field in ("message", "opinion", "conclusion", "audience", "title_direction", "experience"):
                    error = self.check(secret, lambda: DraftOptions(**{field: "상위노출 보장 " + secret}))
                    self.assertIn("비밀번호·키·토큰처럼 보이는 글", error.slots["이유"])
                for field in ("must_include", "exclude", "price_date"):
                    error = self.check(secret, lambda: DraftOptions(**{field: ["무난한 글", secret + " 수익 보장"]}))
                    self.assertIn("비밀번호·키·토큰처럼 보이는 글", error.slots["이유"])

    def test_a_refused_phrase_is_named_by_its_kind_and_the_typed_text_is_not_quoted(self):
        for field in ("message", "opinion", "conclusion", "audience", "title_direction", "experience"):
            with self.subTest(field=field):
                error = refused(**{field: "이 글은 네이버 검색 1위 100% 가능합니다"})
                self.assertIn("결과를 약속하는 표현", error.slots["이유"])
                self.assertIn("검색 1위 보장·가능성", error.slots["이유"])
                self.assertNotIn("검색1위100가능", str(error.detail))
                self.assertNotIn("100", error.slots["이유"] + str(error.detail))

    def test_other_content_refusals_do_not_quote_the_text_either(self):
        for secret in SECRETS:
            for bad in ("<script>" + secret, secret + "<img onerror=x>", "{{" + secret + "}}", secret + "\u0301" * 6, secret * 40):
                with self.subTest(text=bad[:12]):
                    self.check(secret, lambda: DraftOptions(message=bad))
                    self.check(secret, lambda: DraftOptions(must_include=[bad]))

    def test_unknown_or_duplicate_json_keys_are_not_quoted(self):
        for secret in SECRETS:
            with self.subTest(secret=secret[:6]):
                self.check(secret, lambda: DraftOptions.from_dict({secret: "x"}))
                self.check(secret, lambda: DraftOptions.from_dict({"message": "가", secret + "2": 1, secret: 2}))
                self.check(secret, lambda: DraftOptions.from_json('{"' + secret + '": 1}'))
                self.check(secret, lambda: DraftOptions.from_json('{"message": "' + secret + '", "message": "' + secret + '"}'))
                self.check(secret, lambda: DraftOptions.from_json(secret))

    def test_the_unknown_key_message_lists_the_allowed_keys_and_counts_the_rest(self):
        with self.assertRaises(AppError) as caught:
            DraftOptions.from_dict({"nope": 1, "message": "가", "nada": 2})
        reason = caught.exception.slots["이유"]
        self.assertIn("2개", reason)
        self.assertIn("message", reason)
        self.assertNotIn("nope", reason + str(caught.exception.detail))


if __name__ == "__main__":
    unittest.main()
