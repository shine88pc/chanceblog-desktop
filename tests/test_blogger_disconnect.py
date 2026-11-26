"""Blogger 연결 해제·재인증(`service/blogger_flow.py::disconnect`) 시험 — BLOGGER 설계서 BT-40–44 (결정 D-774).

지키는 것:
  1) **연결 해제 = 구글에 취소를 먼저 요청 → 성공해야 보관소의 갱신용 값 한 칸을 지운다**(클라이언트 정보 둘은 남는다 — 항목은 '로그인 필요'). 확인(`--yes`) 없이는 아무것도 하지 않는다.
  2) 취소가 안 되면(오프라인·서버 오류) **아무것도 지우지 않고** 오류로 알린다. '이 PC 의 값만 지움' 은 구글 쪽 로그인 값이 남는다는 것을 한 번 더 확인해야만 되고, 알림이 따라온다.
  3) 항목 지우기(`keys remove`)는 값 묶음 전체를 지운다 — 남는 보관소 값이 없다.
  4) 재인증: 자동 재로그인 없음 · 새 값을 받은 뒤 이전 갱신 값을 취소해 보고 덮어쓴다 · 갱신이 거절되면 '다시 로그인하세요'(테스트 상태의 동의 설정이면 7일마다 만료된다는 안내 꼬리).
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import blogger_flow_support as fs  # noqa: E402
import blogger_support as bs  # noqa: E402

from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.net import loopback  # noqa: E402
from chanceblog_desktop.net.errors import NetError  # noqa: E402
from chanceblog_desktop.service import blogger_flow as flow  # noqa: E402
from chanceblog_desktop.service import connections as cn  # noqa: E402


class DisconnectTest(fs.FlowCase):
    def setUp(self):
        super().setUp()
        self.login()
        self.entry_en = self.entry("blogger_en")
        self.refresh = self.store.get(self.entry_en.ref).reveal("refresh_token")
        self.google.requests.clear()

    def names(self):
        return sorted(self.store.get(self.entry_en.ref).names())

    def test_disconnect_revokes_then_deletes_the_refresh_token_field_and_keeps_client_info(self):
        """BT-40 — F 요청이 먼저, 그 뒤 필드 삭제, `client_id`·`client_secret` 은 남는다."""
        calls = []
        real = cn.detach_refresh_token

        def spy(ctx, entry, **kwargs):
            calls.append(("detach", list(self.google.summaries())))
            return real(ctx, entry, **kwargs)

        with mock.patch.object(cn, "detach_refresh_token", spy):
            result = flow.disconnect(self.ctx, "blogger_en", confirmed=True)
        self.assertEqual((result.was_logged_in, result.revoked), (True, True))
        self.assertEqual(calls, [("detach", ["POST oauth2.googleapis.com/revoke"])], "취소 요청이 보관소 지우기보다 먼저였다")
        self.assertEqual(self.google.requests[0].form(), {"token": self.refresh})
        self.assertEqual(self.names(), ["client_id", "client_secret"])
        self.assertNotIn(self.refresh, self.google.refresh_tokens, "구글에서 취소됐다")
        self.assertEqual(flow.status(self.ctx, "blogger_en").state, "login_needed")
        self.assertNotIn(self.entry_en.entry_id, flow._ACCESS, "메모리의 접근 토큰도 버렸다")
        self.assertClean()
        again = flow.disconnect(self.ctx, "blogger_en", confirmed=True)
        self.assertEqual((again.was_logged_in, again.revoked, self.google.requests), (False, False, self.google.requests[:1]), "이미 로그아웃 상태면 할 일이 없고 요청도 없다")

    def test_without_the_confirmation_nothing_happens(self):
        for value in (False, None, 1, "yes"):
            with self.assertRaises(AppError) as caught:
                flow.disconnect(self.ctx, "blogger_en", confirmed=value)
            self.assertEqual(caught.exception.code, "CONFIRMATION_REQUIRED")
        self.assertEqual((self.google.requests, self.names()), ([], ["client_id", "client_secret", "refresh_token"]))

    def test_an_offline_disconnect_deletes_nothing_and_says_why(self):
        """BT-41 — 취소 실패(오프라인·서버 오류·한도) → 아무것도 지우지 않고 그 오류. 기본은 아무것도 안 지움."""
        cases = ((bs.DISCONNECT, "NETWORK_OFFLINE"), (bs.Reply(503, {"error": "server_error"}), "BLOGGER_SERVER_ERROR"), (bs.Reply(429, {"error": "rate"}), "API_RATE_LIMITED"))
        for reply, code in cases:
            self.cool()
            self.advance(minutes=2)
            self.google.push("revoke", reply)
            with self.subTest(code=code), self.assertRaises(NetError) as caught:
                flow.disconnect(self.ctx, "blogger_en", confirmed=True)
            self.assertEqual(caught.exception.code, code)
            self.assertEqual(self.names(), ["client_id", "client_secret", "refresh_token"], code)
            self.assertIn(self.refresh, self.google.refresh_tokens)
        self.cool()
        self.advance(minutes=2)                                             # 분당 여섯 번 한도(앱 쪽 한도)를 지나게 시계를 민다
        self.env.dial_error = OSError(101, "unreachable")
        with self.assertRaises(NetError) as caught:
            flow.disconnect(self.ctx, "blogger_en", confirmed=True)
        self.assertEqual((caught.exception.code, self.names()), ("NETWORK_OFFLINE", ["client_id", "client_secret", "refresh_token"]))

    def test_this_pc_only_needs_a_second_confirmation_and_leaves_the_google_side_with_a_note(self):
        self.env.dial_error = OSError(101, "unreachable")
        with self.assertRaises(AppError) as caught:
            flow.disconnect(self.ctx, "blogger_en", confirmed=True, this_pc_only=True)
        self.assertEqual(caught.exception.code, "CONFIRMATION_REQUIRED")
        self.assertEqual(self.names(), ["client_id", "client_secret", "refresh_token"])
        result = flow.disconnect(self.ctx, "blogger_en", confirmed=True, this_pc_only=True, understood=True)
        self.assertEqual((result.revoked, result.was_logged_in, self.names()), (False, True, ["client_id", "client_secret"]))
        self.assertTrue(any("보안 설정" in note for note in result.notes), result.notes)
        self.assertEqual(self.google.requests, [], "접속하지 않았다")
        self.assertIn(self.refresh, self.google.refresh_tokens, "구글 쪽 값은 남아 있다(그래서 한 번 더 확인한다)")

    def test_removing_the_entry_deletes_everything_and_leaves_no_blob(self):
        """BT-42 — 항목 지우기 뒤 보관소에 이 항목의 값 묶음이 없다."""
        refs = self.store.list_refs("blogger")
        self.assertEqual(len(refs), 2)
        cn.remove_entry(self.ctx, self.entry_en.entry_id, confirmed=True, keystore=self.store)
        self.assertEqual([ref for ref in self.store.list_refs("blogger") if ref == self.entry_en.ref], [])
        self.assertEqual(len(self.store.list_refs("blogger")), 1, "다른 슬롯은 그대로다")
        self.assertIsNone(flow.find_entry(self.ctx, "blogger_en"))
        self.assertEqual(flow.status(self.ctx, "blogger_en").state, "not_connected")

    def test_the_two_slots_disconnect_independently(self):
        self.login("blogger_ko")
        self.google.requests.clear()
        flow.disconnect(self.ctx, "blogger_ko", confirmed=True)
        self.assertEqual((flow.status(self.ctx, "blogger_ko").logged_in, flow.status(self.ctx, "blogger_en").logged_in), (False, True))
        self.assertEqual(self.google.requests[0].form()["token"] != self.refresh, True, "한글 슬롯의 토큰을 취소했다")


class ReauthTest(fs.FlowCase):
    def test_expiry_shows_the_login_again_message_with_the_seven_day_hint_and_never_logs_in_by_itself(self):
        """BT-43·44 — 갱신 토큰을 서버가 거절하면 `BLOGGER_AUTH_EXPIRED` 와 7일 안내 꼬리. 자동 재로그인은 없다(창구도 브라우저도 열지 않는다)."""
        self.login()
        flow.forget()
        self.google.refresh_tokens.clear()
        opened = []
        with mock.patch.object(loopback, "open_listener", side_effect=lambda: opened.append(1)), self.assertRaises(NetError) as caught:
            flow.check(self.ctx, "blogger_en")
        shown = caught.exception.rendered()
        self.assertEqual((caught.exception.code, opened), ("BLOGGER_AUTH_EXPIRED", []))
        self.assertIn("다시 로그인", shown.action)
        self.assertIn("7일", shown.action)
        self.assertIn("프로덕션", shown.action)
        self.assertEqual(flow.status(self.ctx, "blogger_en").logged_in, True, "값은 그대로 두고 사람이 다시 로그인한다")
        result = self.login()
        self.assertEqual(result.replaced, True)
        flow.check(self.ctx, "blogger_en")

    def test_reauth_when_the_old_token_is_already_dead_still_replaces_it(self):
        self.login()
        self.google.refresh_tokens.clear()                                  # 구글에서 이미 무효 — 취소 요청은 400(이미 무효)이라 성공으로 본다
        self.google.requests.clear()
        result = self.login()
        self.assertEqual(result.replaced, True)
        self.assertEqual(self.google.summaries()[:2], ["POST oauth2.googleapis.com/token", "POST oauth2.googleapis.com/revoke"])
        self.assertEqual(result.notes, ())
        self.assertClean()


if __name__ == "__main__":
    unittest.main()
