"""Blogger API 네 요청(`publish/blogger.py`) 시험 — BLOGGER 설계서 BT-10–19·57 (결정 D-773).

접속 틀의 진짜 클라이언트를 쓰되 소켓은 열리지 않는다 — 전송 자리에 **요청 모양을 엄격히 검사하는 가짜 구글**(`blogger_support.FakeGoogle`)을 끼운다.
지키는 것: 초안 저장 요청에는 초안 질의가 늘 있고 코드 어디서도 뺄 수 없다 · 앱이 보낼 수 있는 요청은 여섯 모양뿐이고 게시·되돌리기·수정·삭제 길은 없다 · 공개(LIVE) 같은 초안이 아닌 답은 즉시 멈춘다 ·
쓰기는 자동 재시도가 없다 · 한도·API 꺼짐·권한·없음·잘못된 요청·서버 오류가 카탈로그의 코드로 갈린다 · 블로그 번호는 숫자뿐이고 응답이 같아야 하며 이름은 태그를 지운 글자로만 보인다.
"""
import ast
import sys
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import blogger_support as bs  # noqa: E402

from chanceblog_desktop import capabilities  # noqa: E402
from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.net import endpoints  # noqa: E402
from chanceblog_desktop.net.errors import NetError  # noqa: E402
from chanceblog_desktop.publish import blogger as api  # noqa: E402
from chanceblog_desktop.publish import blogger_auth as auth  # noqa: E402
from chanceblog_desktop.render.blogger import BloggerPost  # noqa: E402

SRC = ROOT / "src" / "chanceblog_desktop"
POST = BloggerPost("시험 글 제목", "<p>본문 <strong>글</strong></p>", ("가", "나"))
NOW = 1000.0


class World(unittest.TestCase):
    """가짜 구글 + 진짜 접속 틀 + 로그인을 마친 접근 토큰."""

    switches = bs.ALL_SWITCHES

    def setUp(self):
        self.google = bs.FakeGoogle()
        self.env = bs.GoogleHarness(self, self.google, switches=self.switches)
        self.env.__enter__()
        self.addCleanup(self.env.__exit__, None, None, None)
        self.client = self.env.client
        self.refresh = self.google.grant()
        self.token = None
        if "NET_BLOGGER_OAUTH" in self.switches:
            self.token = auth.refresh_access_token(self.client, bs.CLIENT_ID, bs.CLIENT_SECRET, self.refresh, now=NOW)
            self.google.requests.clear()
        self.blog = bs.BLOG_EN

    def fresh(self):
        self.env.usage._state.clear()                                    # 연속 실패 쉬기(`NET_COOLDOWN`)를 비운다 — 한 시험에서 여러 실패를 차례로 본다

    def assertClean(self):
        self.assertEqual(self.google.violations, [], "가짜 서버가 약속과 다른 요청을 받았다")

    def inserts(self):
        return [item for item in self.google.requests if item.method == "POST" and item.path.endswith("/posts")]


def text_of(error):
    shown = error.rendered()
    return " ".join([error.code, repr(error.slots), str(error.detail), shown.message, shown.action, repr(error)])


# ---- B: 초안 저장 ------------------------------------------------------------------------------------------------------------------------
class InsertTest(World):
    def test_isdraft_true_is_always_sent_and_no_code_path_omits_it(self):
        """BT-10 — 초안 저장 요청의 질의는 늘 `isDraft=true` 하나이고, 코드가 질의를 빼려 해도 접속 틀의 모양 검사가 접속하기 전에 막는다."""
        inserted = api.insert_draft(self.client, self.token, self.blog, POST)
        self.assertClean()
        request = self.inserts()[0]
        self.assertEqual(request.query_pairs, [("isDraft", "true")])
        self.assertEqual(request.path, f"/blogger/v3/blogs/{self.blog}/posts")
        self.assertEqual((inserted.status, inserted.blog_id), ("DRAFT", self.blog))
        self.google.requests.clear()
        stripped = lambda use, method, path: f"https://www.googleapis.com{path}"                        # noqa: E731 - 질의를 빼 먹은 주소
        with mock.patch.object(api, "url_for", stripped), self.assertRaises(NetError) as caught:
            api.insert_draft(self.client, self.token, self.blog, POST)
        self.assertEqual((caught.exception.code, self.google.requests), ("UNEXPECTED_ERROR", []))
        for wrong in ("isDraft=false", "isdraft=true", "isDraft=True", "isDraft=true&isDraft=true", "isDraft=true&x=1", "isDraft=1", "isDraft="):
            fake = lambda use, method, path, wrong=wrong: f"https://www.googleapis.com{path}?{wrong}"    # noqa: E731
            with mock.patch.object(api, "url_for", fake), self.assertRaises(NetError):
                api.insert_draft(self.client, self.token, self.blog, POST)
        self.assertEqual(self.google.requests, [], "질의가 다른 요청은 하나도 나가지 않았다")

    def test_the_request_body_has_only_the_planned_keys_and_no_token(self):
        api.insert_draft(self.client, self.token, self.blog, POST)
        request = self.inserts()[0]
        body = request.json()
        self.assertEqual(body, {"kind": "blogger#post", "title": POST.title, "content": POST.html, "labels": ["가", "나"]})
        self.assertNotIn(self.token.reveal().encode(), request.body)
        self.assertEqual(request.headers["authorization"], "Bearer " + self.token.reveal())
        self.assertEqual(request.headers["content-type"], "application/json; charset=UTF-8")
        api.insert_draft(self.client, self.token, self.blog, BloggerPost("제목", "<p>x</p>", ()))
        self.assertEqual(self.inserts()[1].json(), {"kind": "blogger#post", "title": "제목", "content": "<p>x</p>"}, "라벨이 없으면 칸도 없다")
        self.assertClean()

    def test_a_body_over_one_mebibyte_is_refused_before_any_request(self):
        with self.assertRaises(AppError) as caught:
            api.insert_draft(self.client, self.token, self.blog, BloggerPost("제목", "<p>" + "가" * 400000 + "</p>", ()))
        self.assertEqual((caught.exception.code, self.google.requests), ("CONTENT_INVALID", []))

    def test_a_live_or_non_draft_answer_is_an_error_and_stops_everything(self):
        """BT-14 — 공개(LIVE)·예약(SCHEDULED)이면 `BLOGGER_NOT_DRAFT` 로 멈춘다(되돌리는 일은 사람)."""
        for mode in ("ignore_draft", "scheduled"):
            self.google.mode["insert"] = mode
            with self.subTest(mode=mode), self.assertRaises(AppError) as caught:
                api.insert_draft(self.client, self.token, self.blog, POST)
            self.assertEqual(caught.exception.code, "BLOGGER_NOT_DRAFT")
        self.google.mode["insert"] = "lowercase_status"
        self.assertEqual(api.insert_draft(self.client, self.token, self.blog, POST).status, "DRAFT", "대문자로 바꿔 견준다")
        self.assertClean()

    def test_insert_response_validation(self):
        """BT-15 — 글 번호는 숫자 · 블로그 번호가 있으면 요청한 것과 같다 · 주소는 https 또는 빈칸 · 상태가 없으면 빈 글(확인 요청이 보강한다). 모양이 틀리면 서버가 저장했을 수 있다."""
        self.google.mode["insert"] = "no_status"
        self.assertEqual(api.insert_draft(self.client, self.token, self.blog, POST).status, "")
        self.google.mode["insert"] = "with_url"
        self.assertEqual(api.insert_draft(self.client, self.token, self.blog, POST).url, "https://english.example.test/2026/11/x.html")
        for mode in ("blog_mismatch", "bad_id", "bad_url"):
            self.google.mode["insert"] = mode
            with self.subTest(mode=mode), self.assertRaises(NetError) as caught:
                api.insert_draft(self.client, self.token, self.blog, POST)
            self.assertEqual((caught.exception.code, caught.exception.outcome_unknown), ("NET_RESPONSE_INVALID", True), mode)
        self.google.mode["insert"] = "ok"
        for raw in (b"not json", b"[]", b'"x"', b'{"id": 5}', b'{"id": "12", "status": 7}', b'{"id": "12", "blog": "x"}'):
            self.google.push("insert", bs.Reply(200, raw=bs.ns.http_response(200, "OK", (("Content-Type", "application/json"),), raw)))
            with self.subTest(raw=raw), self.assertRaises(NetError) as caught:
                api.insert_draft(self.client, self.token, self.blog, POST)
            self.assertEqual((caught.exception.code, caught.exception.outcome_unknown), ("NET_RESPONSE_INVALID", True))

    def test_the_insert_is_never_retried_automatically(self):
        """BT-16 — 보내기 전 실패(이름 풀이)·보낸 뒤 끊김·5xx·4xx 모두 요청은 한 번뿐이다(401 뒤 갱신해 다시 보내는 것은 흐름의 일이다)."""
        cases = {"끊김": bs.DISCONNECT, "503": bs.google_error(503), "500": bs.google_error(500), "502": bs.google_error(502), "403": bs.google_error(403, "forbidden"), "400": bs.google_error(400),
                 "429": bs.google_error(429, "rateLimitExceeded"), "401": bs.google_error(401), "404": bs.google_error(404)}
        for label, item in cases.items():
            self.google.requests.clear()
            self.fresh()
            self.google.push("insert", item)
            with self.subTest(case=label), self.assertRaises(NetError):
                api.insert_draft(self.client, self.token, self.blog, POST)
            self.assertEqual(len(self.inserts()), 1, label)
        self.google.requests.clear()
        self.fresh()
        dials = len(self.env.dials)
        self.env.dial_error = OSError(101, "unreachable")
        with self.assertRaises(NetError) as caught:
            api.insert_draft(self.client, self.token, self.blog, POST)
        self.assertEqual((caught.exception.code, caught.exception.outcome_unknown, self.google.requests, len(self.env.dials) - dials), ("NETWORK_OFFLINE", False, [], 1), "보내기 전 실패는 서버가 못 봤고 연결도 한 번뿐이다")

    def test_a_server_failure_after_sending_says_the_outcome_is_unknown_and_a_failure_before_does_not(self):
        self.google.push("insert", bs.DISCONNECT)
        with self.assertRaises(NetError) as caught:
            api.insert_draft(self.client, self.token, self.blog, POST)
        self.assertEqual((caught.exception.code, caught.exception.outcome_unknown), ("NETWORK_OFFLINE", True))
        self.fresh()
        self.google.push("insert", bs.google_error(503))
        with self.assertRaises(NetError) as caught:
            api.insert_draft(self.client, self.token, self.blog, POST)
        self.assertEqual((caught.exception.code, caught.exception.outcome_unknown), ("BLOGGER_SERVER_ERROR", True))
        self.fresh()
        self.google.push("insert", bs.google_error(404))
        with self.assertRaises(NetError) as caught:
            api.insert_draft(self.client, self.token, self.blog, POST)
        self.assertEqual((caught.exception.code, caught.exception.outcome_unknown), ("BLOGGER_NOT_FOUND", False))

    def test_error_reasons_map_to_catalog_codes(self):
        """BT-19 — 403 의 한도 사유 여섯 가지→`API_RATE_LIMITED`, API 꺼짐 둘→`BLOGGER_API_NOT_ENABLED`, 그 밖 403→`BLOGGER_PERMISSION_DENIED`, 401·404·400·422·429·5xx."""
        table = []
        table += [(bs.google_error(403, reason), "API_RATE_LIMITED") for reason in sorted(api.LIMIT_REASONS)]
        table += [(bs.google_error(403, "accessNotConfigured"), "BLOGGER_API_NOT_ENABLED"), (bs.google_error(403, "SERVICE_DISABLED"), "BLOGGER_API_NOT_ENABLED"),
                  (bs.google_error(403, "forbidden"), "BLOGGER_PERMISSION_DENIED"), (bs.google_error(403), "BLOGGER_PERMISSION_DENIED"), (bs.google_error(403, "x y"), "BLOGGER_PERMISSION_DENIED"),
                  (bs.google_error(401), "BLOGGER_AUTH_EXPIRED"), (bs.google_error(404), "BLOGGER_NOT_FOUND"), (bs.google_error(400), "REQUEST_INVALID"), (bs.google_error(422), "REQUEST_INVALID"),
                  (bs.google_error(429, "rateLimitExceeded"), "API_RATE_LIMITED"), (bs.google_error(500), "BLOGGER_SERVER_ERROR"), (bs.google_error(503), "BLOGGER_SERVER_ERROR"),
                  (bs.google_error(418), "NET_RESPONSE_INVALID")]
        self.assertEqual(len(api.LIMIT_REASONS), 6)
        for reply, code in table:
            self.fresh()
            self.google.push("insert", reply)
            with self.subTest(code=code, status=reply.status), self.assertRaises(NetError) as caught:
                api.insert_draft(self.client, self.token, self.blog, POST)
            self.assertEqual(caught.exception.code, code)
            self.assertNotIn("CANARY_SERVER_MESSAGE", text_of(caught.exception), "서버가 보낸 문장은 어디에도 없다")

    def test_the_reason_may_come_from_the_details_list_too_and_a_rate_limit_carries_retry_after(self):
        details = bs.Reply(403, {"error": {"code": 403, "message": "CANARY_SERVER_MESSAGE", "status": "PERMISSION_DENIED", "details": [{"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": "SERVICE_DISABLED", "domain": "googleapis.com"}]}})
        self.google.push("insert", details)
        with self.assertRaises(NetError) as caught:
            api.insert_draft(self.client, self.token, self.blog, POST)
        self.assertEqual(caught.exception.code, "BLOGGER_API_NOT_ENABLED")
        self.fresh()
        self.google.push("insert", bs.Reply(429, {"error": {"code": 429}}, headers=(("Retry-After", "120"),)))
        with self.assertRaises(NetError) as caught:
            api.insert_draft(self.client, self.token, self.blog, POST)
        self.assertEqual((caught.exception.code, caught.exception.retry_after), ("API_RATE_LIMITED", 120))
        self.fresh()
        self.google.push("insert", bs.Reply(429, {"error": {"code": 429}}, headers=(("Retry-After", "Wed, 21 Oct 2026 07:28:00 GMT"),)))
        with self.assertRaises(NetError) as caught:
            api.insert_draft(self.client, self.token, self.blog, POST)
        self.assertIsNone(caught.exception.retry_after, "날짜 모양은 읽지 않는다")

    def test_gates_the_write_needs_both_the_upper_and_the_narrow_switch_and_the_login_switch(self):
        """BT-80 의 쓰기 쪽 — 켜진 스위치가 모자라면 요청 본문을 만들기 전에 거절한다."""
        for patches, code in (({"EXTERNAL_WRITE": False}, "EXTERNAL_WRITE_DISABLED"), ({"NET_BLOGGER_DRAFT": False}, "NETWORK_DISABLED"), ({"NET_BLOGGER_OAUTH": False}, "NETWORK_DISABLED")):
            with mock.patch.multiple(capabilities, **patches), self.assertRaises(AppError) as caught:
                api.insert_draft(self.client, self.token, self.blog, POST)
            self.assertEqual(caught.exception.code, code, patches)
        self.assertEqual(self.google.requests, [])


class SwitchOffTest(World):
    switches = ()

    def test_with_every_switch_off_each_public_function_refuses_before_a_connection(self):
        calls = (lambda: api.get_blog(self.client, bs.ns, self.blog), lambda: api.insert_draft(self.client, bs.ns, self.blog, POST), lambda: api.find_drafts(self.client, bs.ns, self.blog),
                 lambda: api.get_post(self.client, bs.ns, self.blog, "1"))
        for call in calls:
            with self.assertRaises(AppError) as caught:
                call()
            self.assertIn(caught.exception.code, ("NETWORK_DISABLED", "EXTERNAL_WRITE_DISABLED"))
        self.assertEqual((self.env.dials, self.google.requests), ([], []))

    def test_only_the_login_switch_opens_the_reads_and_not_the_write(self):
        token = auth.AccessToken("ya29." + "CANARY_ONLY_LOGIN_" + "x" * 20, NOW + 100)
        with mock.patch.object(capabilities, "NET_BLOGGER_OAUTH", True):
            self.google.access_tokens[token.reveal()] = "x"
            self.assertEqual(api.get_blog(self.client, token, self.blog).blog_id, self.blog)
            with self.assertRaises(AppError) as caught:
                api.insert_draft(self.client, token, self.blog, POST)
        self.assertEqual(caught.exception.code, "EXTERNAL_WRITE_DISABLED")
        self.assertEqual(len(self.google.requests), 1)


# ---- A·C·D: 읽기 ------------------------------------------------------------------------------------------------------------------------
class ReadTest(World):
    def test_blog_id_must_be_digits_and_the_answer_must_match(self):
        """BT-57 — 숫자만·응답 `id` 일치·이름은 태그를 지운 글자로만."""
        for bad in ("abc", "12/34", "../x", "1;2", "", "1" * 26, " 12", "12 ", "１２", 12, None, "12?x=1", "12%2f"):
            with self.subTest(bad=repr(bad)), self.assertRaises(AppError) as caught:
                api.get_blog(self.client, self.token, bad)
            self.assertEqual(caught.exception.code, "CONTENT_INVALID")
        self.assertEqual(self.google.requests, [], "길을 만들기 전에 거절했다")
        info = api.get_blog(self.client, self.token, self.blog)
        self.assertEqual((info.blog_id, info.name, info.url), (self.blog, "영문 블로그", "https://english.example.test/"), "이름의 태그는 지워진다")
        self.assertNotIn("<", info.name)
        self.google.mode["blog"] = "id_mismatch"
        with self.assertRaises(NetError) as caught:
            api.get_blog(self.client, self.token, self.blog)
        self.assertEqual(caught.exception.code, "NET_RESPONSE_INVALID")
        for mode in ("bad_url", "long_name"):
            self.google.mode["blog"] = mode
            with self.subTest(mode=mode), self.assertRaises(NetError):
                api.get_blog(self.client, self.token, self.blog)
        self.google.mode["blog"] = "no_url"
        self.assertEqual(api.get_blog(self.client, self.token, self.blog).url, "")
        self.assertClean()

    def test_a_blog_name_full_of_markup_is_shown_as_plain_text_only(self):
        self.google.blogs[self.blog]["name"] = "<script>alert(1)</script><b>이름</b> &amp; 둘 &lt;i&gt;"
        info = api.get_blog(self.client, self.token, self.blog)
        self.assertEqual(info.name, "alert(1)이름 & 둘", "태그는 글자 참조로 숨긴 것까지 지우고 꺾쇠는 남기지 않는다(화면에는 글자로만 보인다)")
        self.assertNotIn("<", info.name + ">")

    def test_an_unknown_blog_is_not_found_and_a_foreign_token_is_refused(self):
        with self.assertRaises(NetError) as caught:
            api.get_blog(self.client, self.token, "55555")
        self.assertEqual(caught.exception.code, "BLOGGER_NOT_FOUND")
        self.fresh()
        stranger = auth.AccessToken("ya29." + "CANARY_STRANGER_" + "x" * 20, NOW + 100)
        with self.assertRaises(NetError) as caught:
            api.get_blog(self.client, stranger, self.blog)
        self.assertEqual(caught.exception.code, "BLOGGER_AUTH_EXPIRED")

    def test_finding_same_title_drafts_reads_at_most_five_well_formed_items(self):
        self.assertEqual(api.find_drafts(self.client, self.token, self.blog), (), "초안이 없으면 빈 튜플")
        for number in range(7):
            self.google.add_post(self.blog, f"제목 {number}")
        self.google.add_post(self.blog, "공개 글", status="LIVE")
        items = api.find_drafts(self.client, self.token, self.blog)
        self.assertEqual(len(items), 5)
        self.assertTrue(all(item.status == "DRAFT" for item in items))
        request = [item for item in self.google.requests if item.path.endswith("/posts") and item.method == "GET"][-1]
        self.assertEqual(request.query, {"status": "DRAFT", "orderBy": "UPDATED", "maxResults": "5", "fetchBodies": "false", "view": "ADMIN"})
        self.assertClean()

    def test_malformed_list_items_are_refused(self):
        self.google.add_post(self.blog, "제목")
        for mode in ("bad_items",):
            self.google.mode["list"] = mode
            with self.assertRaises(NetError) as caught:
                api.find_drafts(self.client, self.token, self.blog)
            self.assertEqual(caught.exception.code, "NET_RESPONSE_INVALID")
        self.google.mode["list"] = "ok"
        for raw in ({"items": [5]}, {"items": [{"id": "x1", "title": "t", "updated": "2026-11-25T09:00:00Z"}]}, {"items": [{"id": "1", "title": 5, "updated": "2026-11-25T09:00:00Z"}]},
                    {"items": [{"id": "1", "title": "t", "updated": "yesterday"}]}, {"items": [{"id": "1", "title": "t"}]}, {"items": [{"id": "1", "title": "t" * 1100, "updated": "2026-11-25T09:00:00Z"}]}):
            self.fresh()
            self.google.push("list", bs.Reply(200, raw))
            with self.subTest(raw=str(raw)[:40]), self.assertRaises(NetError):
                api.find_drafts(self.client, self.token, self.blog)

    def test_checking_one_post_reads_its_status(self):
        post = self.google.add_post(self.blog, "제목")
        self.assertEqual(api.get_post(self.client, self.token, self.blog, post["id"]), api.PostStatus(post["id"], "DRAFT"))
        request = self.google.requests[-1]
        self.assertEqual((request.path, request.query), (f"/blogger/v3/blogs/{self.blog}/posts/{post['id']}", {"view": "ADMIN"}))
        self.google.mode["get"] = "no_status"
        self.assertEqual(api.get_post(self.client, self.token, self.blog, post["id"]).status, "", "상태가 없으면 '확인하지 못함' 이고 실패가 아니다")
        self.google.mode["get"] = "live"
        with self.assertRaises(AppError) as caught:
            api.get_post(self.client, self.token, self.blog, post["id"])
        self.assertEqual(caught.exception.code, "BLOGGER_NOT_DRAFT")
        self.google.mode["get"] = "id_mismatch"
        with self.assertRaises(NetError):
            api.get_post(self.client, self.token, self.blog, post["id"])
        for bad in ("abc", "1/2", "", "9" * 26):
            with self.assertRaises(AppError):
                api.get_post(self.client, self.token, self.blog, bad)
        self.assertClean()

    def test_a_post_that_is_not_there_is_not_found(self):
        self.google.mode["get"] = "ok"
        with self.assertRaises(NetError) as caught:
            api.get_post(self.client, self.token, self.blog, "99999")
        self.assertEqual(caught.exception.code, "BLOGGER_NOT_FOUND")

    def test_times_are_read_as_rfc3339_in_every_offset_form(self):
        from datetime import datetime, timezone
        expected = datetime(2026, 11, 25, 17, 0, 0, tzinfo=timezone.utc)
        for text in ("2026-11-25T09:00:00-08:00", "2026-11-25T17:00:00Z", "2026-11-25T17:00:00.123Z", "2026-11-25T18:00:00+01:00", "2026-11-25t17:00:00z", "2026-11-25T09:00:00.000-08:00"):
            self.assertEqual(api.parse_rfc3339(text), expected, text)
        for bad in ("2026-11-25", "2026-13-25T17:00:00Z", "2026-11-25 17:00:00Z", "2026-11-25T17:00:00", "", None, 5, "2026-11-25T17:00:00+25:00x"):
            self.assertIsNone(api.parse_rfc3339(bad), repr(bad))


# ---- 여섯 모양뿐 ------------------------------------------------------------------------------------------------------------------------
class SixShapesTest(World):
    def test_the_production_table_matches_the_independent_list_of_six_shapes(self):
        """BT-12 — 접속 틀의 표(생산)와 시험 도구가 독립으로 적은 여섯 모양이 같다."""
        production = []
        for use in ("blogger_oauth", "blogger_read", "blogger_draft"):
            endpoint = endpoints.ENDPOINTS[use]
            for route in endpoint.routes:
                production.append((endpoint.host, route.method, route.path_text(), tuple((key, value if isinstance(value, str) else value.pattern) for key, value in route.query), route.content_type or None, route.bearer))
        independent = [(host, method, path.pattern, tuple(query.items()), content_type, bearer) for host, method, path, query, content_type, bearer in bs.SHAPES]
        self.assertEqual(sorted(production, key=repr), sorted(independent, key=repr))
        self.assertEqual(len(production), 6)

    def test_a_full_session_touches_only_the_six_shapes(self):
        post = self.google.add_post(self.blog, "제목")
        api.get_blog(self.client, self.token, self.blog)
        api.insert_draft(self.client, self.token, self.blog, POST)
        api.find_drafts(self.client, self.token, self.blog)
        api.get_post(self.client, self.token, self.blog, post["id"])
        auth.revoke_token(self.client, self.refresh)
        shapes = [self.google.shape_of(request) for request in self.google.requests]
        self.assertEqual(len(shapes), 5)
        self.assertTrue(all(shape is not None and shape in bs.SHAPES for shape in shapes))
        self.assertEqual(len({bs.SHAPES.index(shape) for shape in shapes}), 5, "다섯 요청이 서로 다른 다섯 모양이다")
        self.assertClean()

    def test_publish_revert_delete_update_and_patch_have_no_road(self):
        """초안 전용 — 게시·되돌리기·수정·삭제 길과 방법은 표에 없다. 클라이언트가 접속하기 전에 거절하고 가짜 서버에는 아무것도 닿지 않는다."""
        base = f"https://www.googleapis.com/blogger/v3/blogs/{self.blog}/posts"
        attempts = (("POST", f"{base}/1/publish", None), ("POST", f"{base}/1/revert", None), ("DELETE", f"{base}/1", None), ("PUT", f"{base}/1", b"{}"), ("PATCH", f"{base}/1", b"{}"),
                    ("POST", f"{base}/1?publishDate=2026-01-01", b"{}"), ("POST", f"{base}?isDraft=false", b"{}"), ("POST", f"{base}", b"{}"), ("GET", f"{base}/1/comments", None),
                    ("GET", "https://www.googleapis.com/blogger/v3/users/self/blogs", None), ("POST", f"{base}/1/publish?isDraft=true", b"{}"))
        for method, url, body in attempts:
            use = "blogger_draft" if method != "GET" else "blogger_read"
            with self.subTest(method=method, url=url[-40:]), self.assertRaises(NetError):
                self.client.request(use, method, url, body=body, bearer=self.token.reveal())
        self.assertEqual(self.google.requests, [])
        for use in ("blogger_read", "blogger_oauth"):
            with self.assertRaises(NetError):
                self.client.request(use, "DELETE", f"{base}/1", bearer=self.token.reveal())

    def test_the_source_has_no_function_or_text_for_publish_revert_delete_update_or_patch(self):
        banned_names = {"publish", "revert", "delete", "update", "patch", "unpublish", "remove", "put"}
        for name in ("blogger.py", "blogger_auth.py"):
            tree = ast.parse((SRC / "publish" / name).read_text(encoding="utf-8"))
            defined = {node.name.lower() for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
            self.assertEqual(defined & banned_names, set(), name)
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str) and not node.value.startswith(("\n", " ")) and len(node.value) < 80:
                    for word in ("/publish", "/revert", "DELETE", "PATCH", "PUT"):
                        self.assertNotIn(word, node.value, f"{name}: {node.value[:40]}")
        self.assertEqual({item for item in dir(api.BloggerAdapter) if not item.startswith("_")}, {"exchange", "refresh", "revoke", "get_blog", "insert_draft", "find_drafts", "get_post"})


class IsDraftSourceTest(unittest.TestCase):
    def folded(self, node):
        """상수끼리 이어 붙인 글(`'is' + 'Draft'`·f-문자열의 상수 부분)을 접어 본다 — 못 접으면 None."""
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            left, right = self.folded(node.left), self.folded(node.right)
            return None if left is None or right is None else left + right
        if isinstance(node, ast.JoinedStr):
            parts = [self.folded(item) for item in node.values]
            return None if any(part is None for part in parts) else "".join(parts)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "join" and isinstance(node.args[0], (ast.List, ast.Tuple)):
            separator, items = self.folded(node.func.value), [self.folded(item) for item in node.args[0].elts]
            return None if separator is None or any(item is None for item in items) else separator.join(items)
        return None

    def test_the_word_isdraft_appears_once_in_src_with_a_constant_true(self):
        """BT-11 — AST: `isDraft` 는 `net/endpoints.py` 의 초안 저장 길 표 한 줄(`("isDraft", "true")`)에만 있고 값은 상수 `true` 다. 조립한 글·이름·속성·키워드 인자로도 없다."""
        hits = []
        for path in sorted(SRC.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            docstrings = {id(node.body[0].value) for node in ast.walk(tree) if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body
                          and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant)}
            for node in ast.walk(tree):
                text = self.folded(node) if isinstance(node, (ast.Constant, ast.BinOp, ast.JoinedStr, ast.Call)) else None
                if text and "isdraft" in text.lower() and id(node) not in docstrings:
                    hits.append((path.relative_to(SRC).as_posix(), node.lineno, ast.unparse(node)[:60]))
                label = node.id if isinstance(node, ast.Name) else node.attr if isinstance(node, ast.Attribute) else node.arg if isinstance(node, ast.keyword) else None
                if label and label.lower().replace("_", "") == "isdraft":
                    hits.append((path.relative_to(SRC).as_posix(), node.lineno, "이름 " + label))
        self.assertEqual([(hit[0], hit[2]) for hit in hits], [("net/endpoints.py", "'isDraft'")], f"초안 질의 글자가 표 한 곳에만 있어야 한다: {hits}")
        table = endpoints.ENDPOINTS["blogger_draft"].routes[0].query
        self.assertEqual(table, (("isDraft", "true"),))
        text = (SRC / "net" / "endpoints.py").read_text(encoding="utf-8")
        self.assertIn('query=(("isDraft", "true"),)', text)

    def test_the_scan_is_not_blind(self):
        probes = ("x = 'is' + 'Draft'", "x = f'{a}isDraft'", "x = ''.join(['is', 'Draft'])", "f(isDraft=True)", "obj.isDraft", "isDraft = 'true'", "d = {'isDraft': 'true'}")
        for source in probes:
            seen = False
            for node in ast.walk(ast.parse(source)):
                text = self.folded(node) if isinstance(node, (ast.Constant, ast.BinOp, ast.JoinedStr, ast.Call)) else None
                label = node.id if isinstance(node, ast.Name) else node.attr if isinstance(node, ast.Attribute) else node.arg if isinstance(node, ast.keyword) else None
                seen = seen or bool(text and "isdraft" in text.lower()) or bool(label and label.lower().replace("_", "") == "isdraft")
            self.assertTrue(seen or "{a}" in source, source)


if __name__ == "__main__":
    unittest.main()
