"""응답을 데이터로만 읽는 순수 함수(`net/parse.py`) 시험 — NET 설계서 NT-31(엄격한 JSON)·NT-33(모양 검사와 모르는 필드 버리기)·NT-34(화면에 보일 주소)와 머리글 고르기(R8, D-726).

접속 코드가 없는 순수 함수라 네트워크 없이 돈다. 응답의 글이 어떤 모양이든 `ParseError` 하나(이유 이름표만, 응답의 글 없음)로 끝나는지 본다.
"""
import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

from chanceblog_desktop.net import parse  # noqa: E402
from chanceblog_desktop.net.parse import ParseError  # noqa: E402


class StrictJsonTest(unittest.TestCase):
    def reason(self, data):
        with self.assertRaises(ParseError) as caught:
            parse.read_json(data)
        return caught.exception.reason

    def test_json_reader_is_strict(self):
        """NT-31 — 중복 키·`NaN`·`Infinity`·깊이 초과·정수 길이·BOM·깨진 UTF-8·`RecursionError` 를 모두 거절한다."""
        self.assertEqual(parse.read_json(b'{"a": [1, 2.5, "x", null, true], "b": {"c": -3}}'), {"a": [1, 2.5, "x", None, True], "b": {"c": -3}})
        self.assertEqual(parse.read_json("{\"제목\": \"한글\"}".encode("utf-8")), {"제목": "한글"})
        cases = {
            b'{"a": 1, "a": 2}': "duplicate_key", b'{"a": {"b": 1, "b": 2}}': "duplicate_key", b"NaN": "constant", b"Infinity": "constant", b"-Infinity": "constant", b'[NaN]': "constant",
            b'{"a": 1e999}': "float", b"[1e400]": "float", b"123456789012345678901": "integer", b"-123456789012345678901": "integer", b"[]]": "syntax", b"{": "syntax", b"": "syntax", b"nul": "syntax", b"'a'": "syntax",
            b'{"a": 1,}': "syntax", b"\xef\xbb\xbf{}": "bom", b"\xff\xfe{}": "utf8", b'{"a": "\xff"}': "utf8", b'"\\ud800"': "surrogate", b'{"\\udfff": 1}': "surrogate",
        }
        for data, reason in cases.items():
            with self.subTest(data=data[:30]):
                self.assertEqual(self.reason(data), reason)
        self.assertEqual(parse.read_json(b"12345678901234567890"), 12345678901234567890, "20자리까지는 읽는다")
        self.assertEqual(self.reason(b"1" * 21), "integer")
        with self.assertRaises(ParseError):
            parse.read_json("text")                                    # 바이트가 아니다
        with self.assertRaises(ParseError):
            parse.read_json(None)

    def test_depth_is_limited_to_twenty_and_a_very_deep_text_is_the_same_easy_error(self):
        ok = b"[" * 20 + b"]" * 20
        self.assertIsNotNone(parse.read_json(ok))
        self.assertEqual(self.reason(b"[" * 21 + b"]" * 21), "depth")
        self.assertEqual(self.reason(b'{"a":' * 21 + b"1" + b"}" * 21), "depth")
        deep = b"[" * 200_000 + b"]" * 200_000
        self.assertEqual(self.reason(deep), "depth", "아주 깊은 JSON 의 RecursionError 도 같은 쉬운 오류")
        self.assertEqual(self.reason(b"[" * 200_000), "depth")

    def test_a_huge_string_is_refused(self):
        big = json.dumps("x" * (parse.MAX_STRING_CHARS + 1)).encode("utf-8")
        self.assertEqual(self.reason(big), "string")
        self.assertEqual(len(parse.read_json(json.dumps("x" * parse.MAX_STRING_CHARS).encode("utf-8"))), parse.MAX_STRING_CHARS)

    def test_the_error_carries_only_a_reason_name_and_never_the_text(self):
        secret = b'{"a": 1, "a": "CANARY_NET_SECRET"}'
        with self.assertRaises(ParseError) as caught:
            parse.read_json(secret)
        self.assertNotIn("CANARY", str(caught.exception))
        self.assertNotIn("CANARY", repr(caught.exception.args))
        self.assertEqual(caught.exception.reason, "duplicate_key")


class ShapeToolsTest(unittest.TestCase):
    def test_response_shape_is_checked_before_use_and_unknown_fields_are_dropped(self):
        """NT-33 — 용도별 모양(필드 이름·형·길이·정규식)을 쓰기 전에 검사하고 모르는 필드는 읽지도 않는다."""
        class Spy(dict):
            def __init__(self, *args):
                super().__init__(*args)
                self.read = []

            def __getitem__(self, key):
                self.read.append(key)
                return super().__getitem__(key)

            def get(self, key, default=None):
                self.read.append(key)
                return super().get(key, default)

        body = Spy({"id": "123", "name": "이름", "url": "https://x.example.test/", "evil": "x" * 10, "selfLink": "https://evil.example.test/", "count": 7})
        picked = {"id": parse.expect_text(body, "id", max_chars=25, pattern=r"[0-9]+"), "name": parse.expect_text(body, "name", max_chars=500), "count": parse.expect_int(body, "count", low=0, high=100)}
        self.assertEqual(picked, {"id": "123", "name": "이름", "count": 7})
        self.assertEqual(sorted(body.read), ["count", "id", "name"], "모르는 필드(evil·selfLink·url)는 읽지도 않았다")
        for obj, key, kwargs in (({"id": 5}, "id", dict(max_chars=25)), ({"id": "a" * 26}, "id", dict(max_chars=25)), ({"id": "abc"}, "id", dict(max_chars=25, pattern=r"[0-9]+")), ({}, "id", dict(max_chars=25)),
                                 ({"id": None}, "id", dict(max_chars=25)), ({"id": ["1"]}, "id", dict(max_chars=25))):
            with self.subTest(obj=obj), self.assertRaises(ParseError):
                parse.expect_text(obj, key, **kwargs)
        self.assertEqual(parse.expect_text({}, "url", max_chars=5, required=False), "")
        for value in (True, "5", 5.5, -1, 101, None):
            with self.subTest(value=value), self.assertRaises(ParseError):
                parse.expect_int({"count": value}, "count", low=0, high=100)
        self.assertIsNone(parse.expect_int({}, "count", low=0, high=100, required=False))
        with self.assertRaises(ParseError):
            parse.expect_object([])
        self.assertEqual(parse.expect_object({"a": 1}), {"a": 1})


class DisplayUrlTest(unittest.TestCase):
    def test_display_urls_are_checked_and_never_opened_or_requested(self):
        """NT-34 — 화면에 글자로만 보일 주소: https·길이 500 이하·사용자 정보 없음·ASCII·공백 없음(·호스트 목록이 있으면 정확히 일치). 통과하면 그 글, 아니면 빈 글."""
        good = "https://example.blogspot.com/2026/11/post.html"
        self.assertEqual(parse.check_display_url(good), good)
        self.assertEqual(parse.check_display_url(good, hosts=("example.blogspot.com",)), good)
        self.assertEqual(parse.check_display_url("https://x.example.test:443/a"), "https://x.example.test:443/a")
        bad = ["http://example.blogspot.com/a", "ftp://example.blogspot.com/a", "javascript:alert(1)", "file:///C:/x", "https://user@example.blogspot.com/a", "https://u:p@example.blogspot.com/a", "https://example.blogspot.com/a b",
               "https://example.blogspot.com/a\nb", "https://example.blogspot.com/a\x00", "https://example.blogspot.com/a#frag", "https://example.blogspot.com:8443/a", "https://exämple.blogspot.com/a", "//example.blogspot.com/a",
               "https://" + "a" * 500 + ".test/", "", "   ", None, 5, ["https://example.blogspot.com/"], "https://", "https:///a", "https://example.blogspot.com\\@evil.test/a"]
        for value in bad:
            with self.subTest(value=repr(value)[:40]):
                self.assertEqual(parse.check_display_url(value), "")
        self.assertEqual(parse.check_display_url(good, hosts=("other.blogspot.com",)), "")
        self.assertEqual(parse.check_display_url("https://example.blogspot.com.evil.test/a", hosts=("example.blogspot.com",)), "")
        edge = "https://example.test/" + "a" * 479
        self.assertEqual((len(edge), parse.check_display_url(edge), parse.check_display_url(edge + "a")), (500, edge, ""), "길이 500 은 통과하고 501 은 거절한다")

    def test_the_display_check_never_resolves_opens_or_requests_anything(self):
        import ast
        tree = ast.parse((HERE.parent / "src" / "chanceblog_desktop" / "net" / "parse.py").read_text(encoding="utf-8"))
        imported = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names} | {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        self.assertEqual(sorted(imported - {"__future__"}), ["json", "math", "re", "urllib.parse"], "parse.py 는 접속 코드를 가져오지 않는다")


class HeaderPickTest(unittest.TestCase):
    def test_only_the_documented_headers_are_kept_and_values_are_cleaned(self):
        """R8 — `retry-after`·`content-type`·`content-length`·`x-ratelimit-*` 만 고른다(이동 판정용 `location`·쿠키·서버 식별은 버린다)."""
        items = [("Retry-After", "30"), ("Content-Type", "application/json"), ("Content-Length", "12"), ("X-RateLimit-Remaining", "0"), ("X-RateLimit-Reset", "1700000000"), ("Set-Cookie", "a=b"), ("Location", "https://evil.test/"),
                 ("Server", "x"), ("Via", "y"), ("X-Github-Request-Id", "z"), ("Content-Type", "text/html")]
        picked = parse.pick_headers(items)
        self.assertEqual(sorted(picked), ["content-length", "content-type", "retry-after", "x-ratelimit-remaining", "x-ratelimit-reset"])
        self.assertEqual(picked["content-type"], "application/json", "같은 이름이 둘이면 처음 것")
        self.assertEqual(parse.pick_headers([("Retry-After", "5\r\n\x00x" + "a" * 500)])["retry-after"][:5], "5   x")
        self.assertEqual(len(parse.pick_headers([("Retry-After", "5" * 500)])["retry-after"]), 200)
        self.assertEqual(sorted(parse.pick_headers([("Age", "3"), ("Retry-After", "1")], ("age",))), ["age", "retry-after"])
        self.assertEqual(parse.pick_headers([("Age", "3")]), {})

    def test_retry_after_reads_only_seconds(self):
        for text, value in (("30", 30), ("1", 1), ("86400", 86400), ("0", None), ("86401", None), ("-5", None), ("Wed, 21 Oct 2026 07:28:00 GMT", None), ("", None), ("1e3", None), ("١٢", None), ("1234567", None)):
            with self.subTest(text=text):
                self.assertEqual(parse.retry_after_seconds({"retry-after": text}), value)
        self.assertIsNone(parse.retry_after_seconds({}))
        self.assertIsNone(parse.retry_after_seconds(None))


if __name__ == "__main__":
    unittest.main()
