"""Blogger 로그인·연결 확인·두 슬롯(`service/blogger_flow.py`) 시험 — BLOGGER 설계서 BT-22·30·32·35·43·56·80–83 (결정 D-774).

진짜 창구(루프백 소켓)와 진짜 접속 틀을 쓰되 구글은 **요청 모양을 엄격히 검사하는 가짜**다(`blogger_support.FakeGoogle`) — 소켓은 루프백 말고는 열리지 않고(`Tripwire(loopback_only=True)` 가 센다 — 0 이어야 한다)
가짜 서버가 여섯 모양 밖의 요청을 받으면 `violations` 에 적혀 시험이 빨개진다. 가짜 비밀은 모두 `CANARY_` 로 시작하는 조립한 글이다.
"""
import ast
import sys
import threading
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import blogger_flow_support as fs  # noqa: E402
import blogger_support as bs  # noqa: E402

from chanceblog_desktop import capabilities  # noqa: E402
from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.net import loopback  # noqa: E402
from chanceblog_desktop.net.errors import NetError  # noqa: E402
from chanceblog_desktop.publish import blogger_auth as auth  # noqa: E402
from chanceblog_desktop.service import blogger_flow as flow  # noqa: E402
from chanceblog_desktop.service import connections as cn  # noqa: E402
from chanceblog_desktop.ui.core import open_url  # noqa: E402

SRC = ROOT / "src" / "chanceblog_desktop"


def visible(error):
    shown = error.rendered()
    return " ".join([error.code, repr(error.slots), str(error.detail), shown.message, shown.action, repr(error), str(error)])


class LoginTest(fs.FlowCase):
    def test_a_full_login_keeps_the_refresh_token_only_in_the_keystore(self):
        before = flow.status(self.ctx, "blogger_en")
        self.assertEqual((before.state, before.logged_in, before.has_entry), ("login_needed", False, True))
        result = self.login()
        self.assertEqual((result.slot, result.replaced), ("blogger_en", False))
        after = flow.status(self.ctx, "blogger_en")
        self.assertEqual((after.state, after.logged_in), ("needs_check", True), "로그인만으로는 '연결됨' 이 아니다 — 연결 확인을 사람이 맞다고 해야 한다")
        found = self.store.get(self.entry("blogger_en").ref)
        self.assertEqual(sorted(found.names()), ["client_id", "client_secret", "refresh_token"], "저장 구조는 세 칸 그대로")
        self.assertTrue(found.reveal("refresh_token").startswith("1//0"))
        for path in self.ctx.workspace.root.rglob("*"):
            if path.is_file():
                text = path.read_bytes().decode("utf-8", "replace")
                self.assertNotIn(found.reveal("refresh_token"), text, path.name)
                self.assertNotIn(bs.CLIENT_SECRET, text, path.name)
        self.assertClean()
        self.assertEqual(self.google.summaries(), ["POST oauth2.googleapis.com/token"], "로그인은 교환 요청 한 번뿐이다")
        self.assertEqual(flow.status(self.ctx, "blogger_ko").state, "login_needed", "다른 슬롯은 그대로다")

    def test_the_listener_is_opened_before_the_browser_and_the_url_is_checked_by_both_tables(self):
        order = []
        real = loopback.open_listener

        def spy():
            listener = real()
            order.append(("listening", listener.port))
            return listener

        browser = fs.FakeBrowser(self.google)

        def opener(url):
            order.append(("browser", open_url.check_open_url(url), auth.check_auth_url(url)))
            browser(url)

        with mock.patch.object(loopback, "open_listener", spy):
            flow.login(self.ctx, "blogger_en", open_url=opener)
        browser.join()
        self.assertEqual([item[0] for item in order], ["listening", "browser"], "창구가 먼저 듣고 그 뒤에 브라우저가 열린다(우리가 먼저 — B-01)")
        self.assertEqual(order[1][1:], ("login", []))
        self.assertIn(f"127.0.0.1%3A{order[0][1]}", browser.urls[0])

    def test_when_the_open_table_refuses_the_url_the_browser_is_never_opened(self):
        opened = []
        with mock.patch.object(open_url, "check_open_url", lambda url: None), self.assertRaises(AppError) as caught:
            flow.login(self.ctx, "blogger_en", open_url=opened.append)
        self.assertEqual((caught.exception.code, caught.exception.slots), ("BLOGGER_LOGIN_FAILED", {"이유": auth.REASON_NO_WINDOW}))
        self.assertEqual((opened, self.google.requests), ([], []))

    def test_a_wrong_state_never_reaches_the_exchange(self):
        """BT-22 — 틀린 `state` 의 콜백은 400 이고 교환 요청은 하나도 나가지 않는다. 올바른 콜백이 따로 와야 끝난다."""
        browser = fs.FakeBrowser(self.google, "wrong_state_only")
        with mock.patch.object(loopback, "ACCEPT_TICK", 0.02), self.assertRaises(AppError) as caught:
            flow.login(self.ctx, "blogger_en", open_url=browser, seconds=0.6)
        browser.join()
        self.assertEqual((caught.exception.code, caught.exception.slots), ("BLOGGER_LOGIN_FAILED", {"이유": auth.REASON_TIMEOUT}))
        self.assertTrue(browser.responses[0].startswith(b"HTTP/1.1 400 "))
        self.assertEqual(self.google.requests, [], "교환 요청이 없다")
        self.assertEqual(flow.status(self.ctx, "blogger_en").logged_in, False)
        result = self.login(mode="wrong_state_then_allow")
        self.assertEqual(result.slot, "blogger_en")
        self.assertEqual(self.google.count("/token"), 1)

    def test_hostile_requests_in_the_middle_of_a_login_do_not_end_it_and_the_real_callback_still_logs_in(self):
        """재작업 1 필수-1(안전 검증 S 의 p12) — 서비스 층에서도: 같은 PC 의 다른 프로그램이 이상한 요청(`//[x` 따위와 `state`·`code` 가 맞는 `///callback?…`)을 보내도 로그인은 `ValueError` 로 죽지 않고
        그 요청들은 400 이며 올바른 콜백이 오면 정상으로 끝나 교환 요청은 한 번뿐이다."""
        browser = fs.FakeBrowser(self.google, "hostile_then_allow")
        result = flow.login(self.ctx, "blogger_en", open_url=browser)
        browser.join()
        self.assertEqual((result.slot, result.replaced), ("blogger_en", False))
        self.assertEqual([item.split(b"\r\n", 1)[0] for item in browser.responses], [b"HTTP/1.1 400 Bad Request"] * 4 + [b"HTTP/1.1 200 OK"])
        self.assertEqual(self.google.count("/token"), 1)
        self.assertTrue(flow.status(self.ctx, "blogger_en").logged_in)
        self.assertTrue(flow._LOGIN_LOCK.acquire(blocking=False), "로그인 잠금은 풀려 있다")
        flow._LOGIN_LOCK.release()
        self.assertClean()

    def test_the_user_denying_the_access_stores_nothing(self):
        with self.assertRaises(AppError) as caught:
            self.login(mode="deny")
        self.assertEqual((caught.exception.code, caught.exception.slots), ("BLOGGER_LOGIN_FAILED", {"이유": auth.REASON_DENIED}))
        self.assertEqual((self.google.requests, flow.status(self.ctx, "blogger_en").logged_in), ([], False))

    def test_a_browser_that_cannot_open_is_a_login_failure_without_its_message(self):
        with self.assertRaises(AppError) as caught:
            self.login(mode="broken")
        self.assertEqual(caught.exception.slots, {"이유": auth.REASON_NO_WINDOW})
        self.assertNotIn("CANARY_BROWSER_ERROR", visible(caught.exception))
        self.assertEqual(self.google.requests, [])

    def test_the_window_gives_up_at_the_time_limit_and_on_cancel(self):
        browser = fs.FakeBrowser(self.google, "never")
        with mock.patch.object(loopback, "ACCEPT_TICK", 0.02), self.assertRaises(AppError) as caught:
            flow.login(self.ctx, "blogger_en", open_url=browser, seconds=0.3)
        self.assertEqual(caught.exception.slots, {"이유": auth.REASON_TIMEOUT})
        flag = []
        with mock.patch.object(loopback, "ACCEPT_TICK", 0.02), self.assertRaises(AppError) as caught:
            flow.login(self.ctx, "blogger_en", open_url=lambda url: flag.append(url), cancelled=lambda: bool(flag), seconds=30)
        self.assertEqual(caught.exception.slots, {"이유": auth.REASON_TIMEOUT})
        self.assertEqual(self.google.requests, [])

    def test_a_flood_of_unrelated_requests_ends_the_login(self):
        browser = fs.FakeBrowser(self.google, "never", burst=loopback.MAX_CONNECTIONS)
        with mock.patch.object(loopback, "ACCEPT_TICK", 0.02), self.assertRaises(AppError) as caught:
            flow.login(self.ctx, "blogger_en", open_url=browser, seconds=20)
        browser.join()
        self.assertEqual(caught.exception.slots, {"이유": auth.REASON_FLOOD})

    def test_a_second_login_while_one_runs_is_refused(self):
        """BT-32 — 로그인은 앱 안에서 하나만."""
        entered, release = threading.Event(), threading.Event()
        errors = []

        def slow_open(url):
            entered.set()
            release.wait(10)

        def first():
            try:
                flow.login(self.ctx, "blogger_en", open_url=slow_open, cancelled=lambda: release.is_set(), seconds=20)
            except AppError as error:
                errors.append(error)

        thread = threading.Thread(target=first, daemon=True)
        with mock.patch.object(loopback, "ACCEPT_TICK", 0.02):
            thread.start()
            self.assertTrue(entered.wait(10))
            with self.assertRaises(AppError) as caught:
                flow.login(self.ctx, "blogger_ko", open_url=lambda url: self.fail("두 번째 로그인이 브라우저를 열었다"))
            release.set()
            thread.join(10)
        self.assertEqual((caught.exception.code, caught.exception.slots), ("BLOGGER_LOGIN_FAILED", {"이유": auth.REASON_BUSY}))
        self.assertEqual(len(errors), 1, "첫 로그인은 취소로 끝났다")

    def test_a_login_never_starts_without_client_info_or_a_keystore(self):
        """BT-35 — 클라이언트 정보가 없거나 보관소를 못 열면 창구도 열지 않는다(파일로 대신하지 않는다)."""
        opened = []
        with mock.patch.object(loopback, "open_listener", side_effect=lambda: opened.append(1)):
            ctx = fs.ss.make_ctx(self.tmp / "other", repo=None, clock=fs.ss.Clock())
            with self.assertRaises(AppError) as caught:
                flow.login(ctx, "blogger_en", open_url=lambda url: None)
            self.assertEqual(caught.exception.code, "BLOGGER_NOT_CONNECTED")
            broken = mock.Mock()
            broken.get.side_effect = AppError("KEY_STORE_UNAVAILABLE", detail="시험")
            with self.assertRaises(AppError) as caught:
                flow.login(self.ctx, "blogger_en", open_url=lambda url: None, keystore=broken)
            self.assertEqual(caught.exception.code, "KEY_STORE_UNAVAILABLE")
            with mock.patch.object(type(self.ctx), "get_keystore", side_effect=AppError("KEY_STORE_UNAVAILABLE", detail="시험")), self.assertRaises(AppError) as caught:
                flow.login(self.ctx, "blogger_en", open_url=lambda url: None)
            self.assertEqual(caught.exception.code, "KEY_STORE_UNAVAILABLE")
        self.assertEqual((opened, self.google.requests), ([], []))
        self.assertEqual(sorted(path.name for path in self.ctx.workspace.root.rglob("*") if path.is_file() and "token" in path.name.lower()), [])

    def test_exchange_failures_store_nothing_and_keep_the_entry_logged_out(self):
        """BT-30·31 — 교환이 어떻게 실패해도 보관소에는 아무것도 더해지지 않는다."""
        cases = {"invalid_grant": "BLOGGER_LOGIN_FAILED", "invalid_client": "KEY_AUTH_FAILED", "no_refresh": "BLOGGER_LOGIN_FAILED", "scope_narrow": "BLOGGER_LOGIN_FAILED", "scope_wide": "BLOGGER_LOGIN_FAILED",
                 "bad_type": "NET_RESPONSE_INVALID", "status:503": "BLOGGER_SERVER_ERROR"}
        for mode, code in cases.items():
            self.google.mode["token"] = mode
            self.cool()
            self.advance(minutes=2)
            with self.subTest(mode=mode), self.assertRaises(AppError) as caught:
                self.login()
            self.assertEqual(caught.exception.code, code)
            self.assertEqual(sorted(self.store.get(self.entry("blogger_en").ref).names()), ["client_id", "client_secret"], mode)
            self.assertNotIn("CANARY_", visible(caught.exception))
        self.assertClean()

    def test_logging_in_again_revokes_the_old_token_after_the_new_one_arrives_and_replaces_it(self):
        """BT-43 — 새 값을 받은 뒤 이전 갱신 값을 취소해 보고 덮어쓴다. 취소가 안 돼도 새 값으로 바꾸고 알림만 한다."""
        self.login()
        old = self.store.get(self.entry("blogger_en").ref).reveal("refresh_token")
        self.google.requests.clear()
        result = self.login()
        self.assertEqual(result.replaced, True)
        self.assertEqual(self.google.summaries(), ["POST oauth2.googleapis.com/token", "POST oauth2.googleapis.com/revoke"], "새 값을 받은 뒤에 이전 것을 취소한다")
        self.assertEqual(self.google.requests[1].form(), {"token": old})
        new = self.store.get(self.entry("blogger_en").ref).reveal("refresh_token")
        self.assertIn(new, self.google.refresh_tokens)
        self.assertNotIn(old, self.google.refresh_tokens)
        self.google.mode["revoke"] = "status:503"
        self.cool()
        result = self.login()
        self.assertTrue(any("취소하지 못했어요" in note for note in result.notes), result.notes)
        self.assertEqual(self.store.get(self.entry("blogger_en").ref).reveal("refresh_token") in self.google.refresh_tokens, True, "새 값으로 바뀌었다")
        self.assertClean()

    def test_the_access_token_lives_in_memory_only(self):
        """BT-36 — 접근 토큰은 보관소·파일에 없고 메모리 표에만 있으며 연결 해제·잊기로 사라진다."""
        self.login()
        entry = self.entry("blogger_en")
        token = flow._ACCESS[entry.entry_id]
        for shown in (repr(token), str(token), f"{token}"):
            self.assertNotIn(token.reveal(), shown)
        self.assertNotIn("access_token", self.store.get(entry.ref).names())
        for path in self.ctx.workspace.root.rglob("*"):
            if path.is_file():
                self.assertNotIn(token.reveal(), path.read_bytes().decode("utf-8", "replace"), path.name)
        flow.forget(entry.entry_id)
        self.assertNotIn(entry.entry_id, flow._ACCESS)

    def test_the_status_reads_only_names_and_never_connects(self):
        gets = []
        real = self.store.get
        with mock.patch.object(type(self.store), "get", lambda store, ref: gets.append(ref) or real(ref)):
            flow.status(self.ctx, "blogger_en")
        self.assertEqual(self.google.requests, [])
        self.assertEqual(flow.status(self.ctx, "영문").slot, "blogger_en")
        with self.assertRaises(AppError):
            flow.status(self.ctx, "일본어")
        empty = fs.ss.make_ctx(self.tmp / "empty", repo=None, clock=fs.ss.Clock())
        self.assertEqual(flow.status(empty, "blogger_ko").state, "not_connected")
        broken = mock.Mock()
        broken.get.side_effect = AppError("KEY_STORE_UNAVAILABLE", detail="시험")
        shown = flow.status(self.ctx, "blogger_en", keystore=broken)
        self.assertEqual((shown.state, shown.store_ok), ("needs_check", False))


class CheckTest(fs.FlowCase):
    def test_check_shows_the_blog_name_and_marks_connected_only_when_the_person_confirms(self):
        self.login()
        self.google.requests.clear()
        seen = flow.check(self.ctx, "blogger_en")
        self.assertEqual((seen.blog_id, seen.name, seen.url, seen.confirmed), (fs.BLOG_EN, "영문 블로그", "https://english.example.test/", False))
        self.assertEqual(self.entry("blogger_en").check_result, "", "사람이 맞다고 하기 전에는 '연결됨' 을 적지 않는다")
        self.assertEqual(self.google.summaries(), [f"GET www.googleapis.com/blogger/v3/blogs/{fs.BLOG_EN}"], "접근 토큰은 로그인 때 받은 것을 그대로 쓴다")
        seen = flow.check(self.ctx, "blogger_en", confirmed=True)
        self.assertTrue(seen.confirmed)
        self.assertEqual((self.entry("blogger_en").check_result, bool(self.entry("blogger_en").last_ok_at)), ("ok", True))
        self.assertEqual(flow.status(self.ctx, "blogger_en").state, "connected")
        self.assertClean()

    def test_check_refreshes_the_access_token_when_none_is_in_memory(self):
        self.login()
        flow.forget()
        self.google.requests.clear()
        flow.check(self.ctx, "blogger_en")
        self.assertEqual(self.google.summaries(), ["POST oauth2.googleapis.com/token", f"GET www.googleapis.com/blogger/v3/blogs/{fs.BLOG_EN}"])
        self.assertClean()

    def test_a_401_refreshes_once_and_asks_once_more_and_never_a_third_time(self):
        self.login()
        self.google.access_tokens.clear()                                    # 서버가 토큰을 무효로 만들었다(취소·만료)
        self.google.requests.clear()
        flow.check(self.ctx, "blogger_en")
        self.assertEqual(self.google.summaries(), [f"GET www.googleapis.com/blogger/v3/blogs/{fs.BLOG_EN}", "POST oauth2.googleapis.com/token", f"GET www.googleapis.com/blogger/v3/blogs/{fs.BLOG_EN}"])
        self.google.requests.clear()
        self.advance(minutes=2)                                              # 1분 창(앱이 스스로 두는 한도)을 다시 비운다
        self.google.push("blog", bs.google_error(401), bs.google_error(401))
        self.cool()
        with self.assertRaises(NetError) as caught:
            flow.check(self.ctx, "blogger_en")
        self.assertEqual(caught.exception.code, "BLOGGER_AUTH_EXPIRED")
        self.assertEqual(len([item for item in self.google.requests if item.method == "GET"]), 2, "읽기도 두 번에서 멈춘다")

    def test_a_refresh_token_the_server_refused_means_login_again_and_nothing_logs_in_by_itself(self):
        """B-15·BT-43 — 갱신이 거절되면 `BLOGGER_AUTH_EXPIRED` 뿐이다. 브라우저를 열지도 창구를 열지도 않는다."""
        self.login()
        flow.forget()
        self.google.refresh_tokens.clear()
        opened = []
        with mock.patch.object(loopback, "open_listener", side_effect=lambda: opened.append(1)), self.assertRaises(NetError) as caught:
            flow.check(self.ctx, "blogger_en")
        self.assertEqual((caught.exception.code, opened), ("BLOGGER_AUTH_EXPIRED", []))
        self.assertEqual(self.entry("blogger_en").check_result, "error")
        self.assertIn("7일", caught.exception.rendered().action, "테스트 상태의 동의 설정이면 7일마다 만료된다는 안내 꼬리(BT-44)")

    def test_check_needs_a_login_a_digits_only_blog_number_and_the_right_blog(self):
        with self.assertRaises(AppError) as caught:
            flow.check(self.ctx, "blogger_en")
        self.assertEqual(caught.exception.code, "BLOGGER_NOT_CONNECTED")
        self.login()
        for bad in ("", "my-blog", "https://example.test/blog", "12a34"):
            self.set_blog("blogger_en", bad)
            with self.subTest(blog_ref=bad), self.assertRaises(AppError) as caught:
                flow.check(self.ctx, "blogger_en")
            self.assertEqual(caught.exception.code, "CONTENT_INVALID")
        self.set_blog("blogger_en", "55555")
        with self.assertRaises(NetError) as caught:
            flow.check(self.ctx, "blogger_en")
        self.assertEqual(caught.exception.code, "BLOGGER_NOT_FOUND")
        self.cool()
        self.set_blog("blogger_en", fs.BLOG_EN)
        self.google.mode["blog"] = "status:403:forbidden"
        with self.assertRaises(NetError) as caught:
            flow.check(self.ctx, "blogger_en")
        self.assertEqual(caught.exception.code, "BLOGGER_PERMISSION_DENIED")
        self.assertIn("영문·한글 블로그는 계정이 다르니", caught.exception.rendered().action)
        self.assertEqual(self.entry("blogger_en").check_result, "error")

    def test_two_slots_use_two_entries_and_never_mix_tokens_or_blog_ids(self):
        """BT-56 — 영문은 영문 항목의 토큰·영문 블로그 번호로만, 한글은 한글 쪽으로만 나간다."""
        self.login_both()
        english, korean = self.approve("blogger_en", "English post"), self.approve("blogger_ko", "한글 글")
        self.save(english, "blogger_en")
        self.save(korean, "blogger_ko")
        by_blog = {}
        for request in self.google.requests:
            if request.host == "www.googleapis.com":
                by_blog.setdefault(request.path.split("/")[4], set()).add(request.bearer)
        self.assertEqual(sorted(by_blog), sorted([fs.BLOG_EN, fs.BLOG_KO]))
        self.assertTrue(by_blog[fs.BLOG_EN].isdisjoint(by_blog[fs.BLOG_KO]), "두 블로그에 같은 토큰이 쓰이지 않았다")
        owners = {blog: {self.google.access_tokens[token] for token in tokens} for blog, tokens in by_blog.items()}
        self.assertEqual(owners[fs.BLOG_EN], {self.store.get(self.entry("blogger_en").ref).reveal("refresh_token")})
        self.assertEqual(owners[fs.BLOG_KO], {self.store.get(self.entry("blogger_ko").ref).reveal("refresh_token")})
        self.assertEqual([post["title"] for post in self.google.drafts(fs.BLOG_EN)], ["English post"])
        self.assertEqual([post["title"] for post in self.google.drafts(fs.BLOG_KO)], ["한글 글"])
        for request in self.google.requests:
            if request.path == "/token":
                client = request.form()["client_id"]
                self.assertIn(client, (fs.CLIENT_ID, fs.CLIENT_ID_KO))
        self.assertClean()

    def test_when_one_slot_is_blocked_by_the_limit_the_other_blog_is_never_used_instead(self):
        """제공자 전환 금지 — 영문 항목이 한도로 막혀도 영문 글이 한글 블로그로 가지 않는다."""
        from chanceblog_desktop.service import quota
        self.login_both()
        self.exhaust_the_day(self.entry("blogger_en"))
        english = self.approve("blogger_en", "English post")
        with self.assertRaises(AppError) as caught:
            self.save(english, "blogger_en")
        self.assertEqual(caught.exception.code, "API_RATE_LIMITED")
        self.assertEqual(self.google.requests, [], "한글 쪽으로도 영문 쪽으로도 한 건도 나가지 않았다")
        self.assertEqual((self.google.drafts(fs.BLOG_EN), self.google.drafts(fs.BLOG_KO)), ([], []))
        self.assertEqual(self.variant(english).status, "APPROVED")
        korean = self.approve("blogger_ko", "한글 글")
        self.save(korean, "blogger_ko")
        self.assertEqual(len(self.google.drafts(fs.BLOG_KO)), 1, "한글 항목은 따로 센다")

    def exhaust_the_day(self, entry):
        """항목의 하루 한도를 다 쓴다(1분 창에 걸리지 않게 다섯 번마다 시계를 앞으로 보낸다) → 쓴 횟수."""
        from chanceblog_desktop.service import quota
        guard = quota.QuotaGuard(self.ctx)
        used = 0
        while True:
            if used % 5 == 0:
                self.advance(minutes=2)
            if not hasattr(guard.acquire_entry(entry, calls=1, priority=quota.CRITICAL, kind="blogger_fill"), "entry_id"):
                self.assertLessEqual(used, cn.BLOGGER_DAY_LIMIT)
                return used
            used += 1
            self.assertLessEqual(used, cn.BLOGGER_DAY_LIMIT)

    def test_the_per_minute_limit_stops_a_burst(self):
        from chanceblog_desktop.service import quota
        self.login()
        self.advance(minutes=2)                                                    # 로그인의 요청 한 건이 지난 뒤부터 센다
        guard = quota.QuotaGuard(self.ctx)
        entry = self.entry("blogger_en")
        for _ in range(cn.BLOGGER_MINUTE_LIMIT):
            self.assertTrue(hasattr(guard.acquire_entry(entry, calls=1, priority=quota.CRITICAL, kind="blogger_fill"), "entry_id"))
        with self.assertRaises(AppError) as caught:
            flow.check(self.ctx, "blogger_en")
        self.assertEqual(caught.exception.code, "API_RATE_LIMITED")
        self.assertIn("한국 시간", caught.exception.rendered().message)
        self.advance(minutes=2)
        flow.check(self.ctx, "blogger_en")


class GateAndEntryPointTest(fs.FlowCase):
    switches = ()

    def test_every_blogger_entry_point_passes_its_gates_as_its_first_statements(self):
        """BT-80 — 로그인·연결 확인·연결 해제는 첫 문장이 `require_net`, 초안 저장은 첫 두 문장이 `require_external_write` + `require_net("blogger_draft", …)` 이다.
        그 뒤에는 구분 이름·글 번호를 **읽기만 하며** 풀고(없는 번호는 확인을 묻기 전에 알린다 — 기존 시험 `test_service_echo` 가 번호 자리 명령에 요구한다) 그다음이 확인이며, 확인은 저널·접속·쓰기가 시작되는 잠금 안으로 들어가기 전에 있다."""
        tree = ast.parse((SRC / "service" / "blogger_flow.py").read_text(encoding="utf-8"))
        functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}

        def statements(name):
            return [ast.unparse(node) for node in functions[name].body if not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant))]

        self.assertEqual(statements("login")[0], "capabilities.require_net('blogger_oauth', 'Blogger 로그인')")
        self.assertEqual(statements("check")[0], "capabilities.require_net('blogger_read', 'Blogger 연결 확인')")
        self.assertEqual(statements("disconnect")[0], "capabilities.require_net('blogger_oauth', 'Blogger 연결 해제')")
        save = statements("save_draft")
        self.assertEqual(save[:2], ["capabilities.require_external_write('Blogger 초안 저장')", "capabilities.require_net('blogger_draft', 'Blogger 초안 저장')"])
        confirm_at = next(index for index, text in enumerate(save) if text.startswith("require_confirmation(confirmed,"))
        lock_at = next(index for index, text in enumerate(save) if text.startswith("with _slot_lock("))
        self.assertLess(confirm_at, lock_at, "확인은 저널·접속·쓰기가 시작되는 잠금 안으로 들어가기 전에 있다")
        self.assertEqual(save[2:confirm_at], ["slot = slot_key(slot)", "with ctx.store() as store:\n    project_id = resolve_id(store, project_text)"], "관문과 확인 사이에는 읽기뿐이다")
        for module, names in (("publish/blogger.py", {"get_blog": "USE_READ", "find_drafts": "USE_READ", "get_post": "USE_READ"}), ("publish/blogger_auth.py", {"exchange_code": "USE", "refresh_access_token": "USE", "revoke_token": "USE", "begin_login": "USE"})):
            inner = {node.name: node for node in ast.parse((SRC / module).read_text(encoding="utf-8")).body if isinstance(node, ast.FunctionDef)}
            for name, use in names.items():
                body = [ast.unparse(node) for node in inner[name].body if not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant))]
                self.assertTrue(body[0].startswith(f"capabilities.require_net({use},"), f"{module}:{name}")
        insert = [ast.unparse(node) for node in {n.name: n for n in ast.parse((SRC / "publish" / "blogger.py").read_text(encoding="utf-8")).body if isinstance(n, ast.FunctionDef)}["insert_draft"].body
                  if not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant))]
        self.assertEqual(insert[:2], ["capabilities.require_external_write('Blogger 초안 저장')", "capabilities.require_net(USE_DRAFT, 'Blogger 초안 저장')"])

    def test_with_every_switch_off_each_command_refuses_before_a_window_a_connection_or_a_file(self):
        """BT-81 — 기본 빌드에서 새 흐름은 소켓·접속·파일을 만들지 않는다."""
        before = sorted(path.relative_to(self.tmp).as_posix() for path in self.tmp.rglob("*"))
        opened, spy = [], []
        calls = {"login": lambda: flow.login(self.ctx, "blogger_en", open_url=opened.append), "check": lambda: flow.check(self.ctx, "blogger_en"), "disconnect": lambda: flow.disconnect(self.ctx, "blogger_en", confirmed=True),
                 "save": lambda: flow.save_draft(self.ctx, "abcd", "blogger_en", confirmed=True)}
        with mock.patch.object(loopback, "open_listener", side_effect=lambda: spy.append(1)):
            for label, call in calls.items():
                with self.subTest(command=label), self.assertRaises(AppError) as caught:
                    call()
                self.assertIn(caught.exception.code, ("NETWORK_DISABLED", "EXTERNAL_WRITE_DISABLED"), label)
        self.assertEqual((opened, spy, self.env.dials, self.google.requests, self.wire.calls), ([], [], [], [], []))
        self.assertEqual(sorted(path.relative_to(self.tmp).as_posix() for path in self.tmp.rglob("*")), before, "파일도 만들지 않았다")
        self.assertEqual(flow.status(self.ctx, "blogger_en").state, "login_needed", "읽기만 하는 상태 보기는 스위치와 상관없이 된다")


class SwitchesAloneTest(fs.FlowCase):
    switches = ()

    def test_only_the_switches_without_credentials_make_zero_calls(self):
        """BT-82 — 스위치만 켜고 항목이 없으면(또는 로그인하지 않았으면) 접속 0."""
        empty = fs.ss.make_ctx(self.tmp / "empty", repo=None, clock=fs.ss.Clock())
        with mock.patch.multiple(capabilities, EXTERNAL_WRITE=True, NET_BLOGGER_OAUTH=True, NET_BLOGGER_DRAFT=True):
            for call in (lambda: flow.login(empty, "blogger_en", open_url=lambda url: None), lambda: flow.check(empty, "blogger_en"), lambda: flow.disconnect(empty, "blogger_en", confirmed=True),
                         lambda: flow.save_draft(empty, "abcd", "blogger_en", confirmed=True)):
                with self.assertRaises(AppError) as caught:
                    call()
                self.assertIn(caught.exception.code, ("BLOGGER_NOT_CONNECTED", "CONTENT_NOT_FOUND"))
            with self.assertRaises(AppError) as caught:
                flow.check(self.ctx, "blogger_en")                                 # 항목은 있지만 로그인하지 않았다
            self.assertEqual(caught.exception.code, "BLOGGER_NOT_CONNECTED")
        self.assertEqual((self.env.dials, self.google.requests, self.wire.calls), ([], [], []))

    def test_the_login_switch_alone_opens_reads_but_the_write_needs_both_the_upper_and_the_narrow_switch(self):
        with mock.patch.object(capabilities, "NET_BLOGGER_OAUTH", True):
            with self.assertRaises(AppError) as caught:
                flow.save_draft(self.ctx, "abcd", "blogger_en", confirmed=True)
            self.assertEqual(caught.exception.code, "EXTERNAL_WRITE_DISABLED")
            with mock.patch.object(capabilities, "EXTERNAL_WRITE", True), self.assertRaises(AppError) as caught:
                flow.save_draft(self.ctx, "abcd", "blogger_en", confirmed=True)
            self.assertEqual(caught.exception.code, "NETWORK_DISABLED", "윗 스위치만으로는 부족하다 — 좁은 스위치도 켜져야 한다")


if __name__ == "__main__":
    unittest.main()
