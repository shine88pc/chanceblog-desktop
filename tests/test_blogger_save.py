"""Blogger 초안 저장(`service/blogger_flow.py::save_draft`) 시험 — BLOGGER 설계서 BT-10·14·16–18·32·50–56 의 흐름 쪽과 7절 '탐침' 표(초안 전용·재시도·중복·로컬 이미지·HTML)(결정 D-774).

진짜 접속 틀 + **요청 모양을 엄격히 검사하는 가짜 구글**(`FakeGoogle`) + 가짜 보관소·가짜 브라우저. 소켓은 루프백 말고는 열리지 않는다(감시가 센다). 지키는 것:
  1) 확인 없이는 아무것도 하지 않고, 승인한 현재 판의 글만 보낸다 · 막힌 글(키 모양·이 PC 경로·위험한 표기·이 PC 의 사진)은 한 건도 보내지 않는다.
  2) 쓰기는 요청 한 건이다: 보내기 전 실패·4xx 는 다시 보내지 않고, 보낸 뒤 끊기거나 5xx 면 **같은 제목의 초안을 먼저 찾아** 정확히 하나일 때만 이어받고 아니면 멈춘다(중복 초안 없음). 401 뒤 갱신해 한 번 다시 보내는 것이 유일한 예외다.
  3) 공개(LIVE) 같은 초안이 아닌 답은 즉시 멈추고 글 상태는 실패로 바뀐다 · 저널은 보내기 전에 쓰고 해시뿐이다 · 한도는 항목마다.
"""
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import blogger_flow_support as fs  # noqa: E402
import blogger_support as bs  # noqa: E402

from chanceblog_desktop import capabilities  # noqa: E402
from chanceblog_desktop.content.model import Asset  # noqa: E402
from chanceblog_desktop.content.store import Store  # noqa: E402
from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.net.errors import NetError  # noqa: E402
from chanceblog_desktop.render.blogger import HeroImage  # noqa: E402
from chanceblog_desktop.service import blogger_flow as flow  # noqa: E402
from chanceblog_desktop.service import projects  # noqa: E402
from chanceblog_desktop.ui.core.attribution import PhotoCredit  # noqa: E402

HERO_URL = "https://images.unsplash.com/photo-1500000000000-aaaaaaaaaaaa?w=1200"
KEY = fs.ss.KEY


class SaveCase(fs.FlowCase):
    def setUp(self):
        super().setUp()
        self.login("blogger_en")
        self.google.requests.clear()
        self.pid = self.approve("blogger_en")

    def stored(self):
        return self.google.drafts(fs.BLOG_EN)

    def assertNothingSent(self, slot="blogger_en"):
        self.assertEqual((self.google.requests, self.journals(), self.stored()), ([], [], []))
        self.assertEqual(self.variant(self.pid, slot).status, "APPROVED")


class HappyPathTest(SaveCase):
    def test_an_approved_post_is_saved_as_a_draft_with_two_requests_and_the_state_follows(self):
        result = self.save(self.pid)
        self.assertEqual((result.slot, result.adopted, result.verified), ("blogger_en", False, True))
        self.assertEqual(self.google.summaries(), [f"POST www.googleapis.com/blogger/v3/blogs/{fs.BLOG_EN}/posts?isDraft=true", f"GET www.googleapis.com/blogger/v3/blogs/{fs.BLOG_EN}/posts/{result.post_id}?view=ADMIN"])
        variant = self.variant(self.pid)
        self.assertEqual((variant.status, variant.remote_id, variant.error_code), ("DRAFT_SAVED", result.post_id, None))
        post = self.stored()[0]
        self.assertEqual((post["title"], post["content"], post["status"]), (fs.TITLE, "<h2>소제목</h2><p>에너지를 아끼는 작은 습관은 매일 조금씩 실천할 때 가장 오래 갑니다. 이 글은 시험용 본문입니다.</p><p>둘째 문단입니다.</p>", "DRAFT"))
        self.assertEqual(self.journals(), [], "저장이 끝나면 저널을 지운다")
        self.assertEqual(len(self.inserts()), 1)
        self.assertClean()

    def test_labels_and_a_hero_photo_are_sent_and_checked(self):
        hero = HeroImage(HERO_URL, PhotoCredit("Jane Doe", "https://unsplash.com/photos/abc123", "https://unsplash.com/@jane"), "대표 사진")
        self.save(self.pid, tags=("에너지", "에너지", "생활 습관"), hero=hero)
        body = self.inserts()[0].json()
        self.assertEqual(body["labels"], ["에너지", "생활 습관"])
        self.assertTrue(body["content"].startswith('<div style="text-align:center;margin:0 0 1.5em;"><img src="https://images.unsplash.com/'))
        self.assertIn("Photo by <a", body["content"])
        self.assertClean()

    def test_the_request_body_has_no_token_secret_or_local_path(self):
        self.save(self.pid)
        request = self.inserts()[0]
        for secret in (bs.CLIENT_SECRET, self.store.get(self.entry("blogger_en").ref).reveal("refresh_token"), request.bearer, str(self.tmp), str(self.ctx.workspace.root)):
            self.assertNotIn(secret.encode("utf-8"), request.body)
        self.assertEqual(set(request.json()), {"kind", "title", "content"})
        self.assertEqual(sorted(request.headers), sorted(["host", "user-agent", "accept", "accept-encoding", "connection", "content-type", "content-length", "authorization"]))


class NothingHappensTest(SaveCase):
    def test_without_the_confirmation_nothing_happens(self):
        with self.assertRaises(AppError) as caught:
            self.save(self.pid, confirmed=False)
        self.assertEqual(caught.exception.code, "CONFIRMATION_REQUIRED")
        for value in (None, 1, "yes", "True"):
            with self.assertRaises(AppError):
                self.save(self.pid, confirmed=value)
        self.assertNothingSent()

    def test_only_an_approved_post_of_the_current_revision_is_sent(self):
        plain = projects.new_project(self.ctx, "승인 안 한 글", fs.BODY_MARKDOWN).project_id
        edited = self.approve("blogger_en", "고칠 글")
        projects.edit_project(self.ctx, edited, markdown="고친 본문입니다. " * 5)
        saved = self.approve("blogger_en", "이미 저장한 글")
        self.save(saved)
        self.google.requests.clear()
        for label, pid, slot in (("승인 전", plain, "blogger_en"), ("승인 뒤 원고를 고침", edited, "blogger_en"), ("이미 저장함", saved, "blogger_en"), ("다른 슬롯은 승인하지 않음", self.pid, "blogger_ko")):
            with self.subTest(case=label), self.assertRaises(AppError) as caught:
                self.save(pid, slot)
            self.assertEqual(caught.exception.code, "STATUS_TRANSITION_INVALID", label)
        self.assertEqual(self.google.requests, [])
        self.assertEqual(self.variant(edited).status, "DRAFT_GENERATED")

    def test_an_unknown_post_a_wrong_slot_and_a_missing_login_stop_before_any_request(self):
        with self.assertRaises(AppError) as caught:
            self.save("zzzzzzzz")
        self.assertEqual(caught.exception.code, "CONTENT_NOT_FOUND")
        with self.assertRaises(AppError) as caught:
            self.save(self.pid, "일본어")
        self.assertEqual(caught.exception.code, "CONTENT_INVALID")
        korean = self.approve("blogger_ko", "한글 글")
        with self.assertRaises(AppError) as caught:
            self.save(korean, "blogger_ko")                                              # 한글 슬롯은 로그인하지 않았다
        self.assertEqual(caught.exception.code, "BLOGGER_NOT_CONNECTED")
        self.set_blog("blogger_en", "")
        with self.assertRaises(AppError) as caught:
            self.save(self.pid)
        self.assertEqual(caught.exception.code, "CONTENT_INVALID")
        self.assertEqual((self.google.requests, self.journals()), ([], []))

    def test_blocked_posts_are_never_sent(self):
        """키 모양·이 PC 의 폴더 경로·위험한 표기·이 PC 의 사진은 한 건도 보내지 않는다 — 저널도 만들지 않는다."""
        cases = {
            "키 모양": (fs.BODY_MARKDOWN + f"\n\n여기에 {KEY} 를 붙였어요.\n", "SECRET_SHAPE_FOUND"),
            "이 PC 경로": (fs.BODY_MARKDOWN + "\n\n파일은 C:" + chr(92) + "Users" + chr(92) + "CANARY_USER" + chr(92) + "a.txt 에 있어요.\n", "CHECK_FAILED"),
            "HTML 태그": (fs.BODY_MARKDOWN + "\n\n<script>alert(1)</script>\n", "CHECK_FAILED"),
            "위험한 주소": (fs.BODY_MARKDOWN + "\n\n[누르기](javascript:alert(1))\n", "CHECK_FAILED"),
            "템플릿 표기": (fs.BODY_MARKDOWN + "\n\n{{ site.password }}\n", "CHECK_FAILED"),
            "이 PC 의 사진": (fs.BODY_MARKDOWN + "\n\n![사진](C:" + chr(92) + "photos" + chr(92) + "a.png)\n", "BLOGGER_IMAGE_UNSUPPORTED"),
            "상대 경로 사진": (fs.BODY_MARKDOWN + "\n\n![사진](./a.png)\n", "BLOGGER_IMAGE_UNSUPPORTED"),
        }
        for label, (markdown, code) in cases.items():
            pid = self.approve("blogger_en", "막힌 글 " + label)
            self.poison(pid, markdown)
            with self.subTest(case=label), self.assertRaises(AppError) as caught:
                self.save(pid)
            self.assertEqual(caught.exception.code, code, label)
            shown = caught.exception.rendered()
            for secret in (KEY, "CANARY_USER", "alert(1)"):
                self.assertNotIn(secret, shown.message + shown.action + str(caught.exception.detail) + repr(caught.exception.slots), label)
            self.assertEqual((self.google.requests, self.journals(), self.variant(pid).status), ([], [], "APPROVED"), label)

    def test_a_local_photo_asset_stops_the_post_and_its_name_is_nowhere(self):
        pid = self.approve("blogger_en", "사진 글", assets=(Asset("CANARY_photo_name.png"),))
        with self.assertRaises(AppError) as caught:
            self.save(pid)
        self.assertEqual((caught.exception.code, caught.exception.slots), ("BLOGGER_IMAGE_UNSUPPORTED", {"사진 수": "1"}))
        self.assertNotIn("CANARY_photo_name", caught.exception.rendered().message + str(caught.exception.detail))
        self.assertEqual((self.google.requests, self.journals()), ([], []))


class DraftOnlyTest(SaveCase):
    def test_a_live_answer_stops_everything_and_marks_the_post_failed(self):
        """BT-14·B-09 — 서버가 초안 표시를 무시하고 공개(LIVE)로 답하면 그 즉시 멈춘다: 확인 요청도 하지 않고 다시 보내지 않으며 글 상태는 실패다."""
        self.google.mode["insert"] = "ignore_draft"
        with self.assertRaises(AppError) as caught:
            self.save(self.pid)
        self.assertEqual(caught.exception.code, "BLOGGER_NOT_DRAFT")
        self.assertEqual((len(self.inserts()), self.google.count("?view=ADMIN")), (1, 0))
        variant = self.variant(self.pid)
        self.assertEqual((variant.status, variant.error_code, variant.remote_id), ("PUBLISH_FAILED", "BLOGGER_NOT_DRAFT", None))
        self.assertEqual(self.journals(), [])
        self.assertIn("공개", caught.exception.rendered().action)
        with self.assertRaises(AppError) as again:
            self.save(self.pid)
        self.assertEqual(again.exception.code, "STATUS_TRANSITION_INVALID", "다시 검토·승인하기 전에는 보내지 않는다")
        self.assertEqual(len(self.inserts()), 1)

    def test_a_scheduled_answer_is_not_a_draft_either(self):
        self.google.mode["insert"] = "scheduled"
        with self.assertRaises(AppError) as caught:
            self.save(self.pid)
        self.assertEqual((caught.exception.code, self.variant(self.pid).status), ("BLOGGER_NOT_DRAFT", "PUBLISH_FAILED"))

    def test_a_live_answer_from_the_check_request_stops_too(self):
        self.google.mode["get"] = "live"
        with self.assertRaises(AppError) as caught:
            self.save(self.pid)
        self.assertEqual(caught.exception.code, "BLOGGER_NOT_DRAFT")
        self.assertEqual((self.variant(self.pid).status, len(self.inserts()), self.journals()), ("PUBLISH_FAILED", 1, []))

    def test_a_missing_status_in_one_or_both_answers_is_a_warning_and_never_a_failure(self):
        self.google.mode["insert"] = "no_status"
        result = self.save(self.pid)
        self.assertTrue(result.verified, "저장 답에 상태가 없어도 확인 요청이 DRAFT 라고 답했다")
        second = self.approve("blogger_en", "둘째 글")
        self.cool()
        self.google.mode["get"] = "no_status"
        result = self.save(second)
        self.assertFalse(result.verified)
        self.assertTrue(any("알려 주지 않았어요" in note for note in result.notes), result.notes)
        self.assertEqual(self.variant(second).status, "DRAFT_SAVED")

    def test_when_the_check_request_fails_but_the_save_answer_said_draft_the_post_is_saved_with_a_note(self):
        self.google.push("get", bs.google_error(503))
        result = self.save(self.pid)
        self.assertTrue(result.verified and any("다시 확인하는 요청이 끝나지 못했어요" in note for note in result.notes))
        self.assertEqual(self.variant(self.pid).status, "DRAFT_SAVED")

    def test_when_neither_answer_says_draft_and_the_check_fails_the_outcome_is_unknown(self):
        self.google.mode["insert"] = "no_status"
        self.google.push("get", bs.google_error(503))
        with self.assertRaises(AppError) as caught:
            self.save(self.pid)
        self.assertEqual(caught.exception.code, "BLOGGER_DRAFT_UNKNOWN")
        self.assertEqual((self.variant(self.pid).status, self.journals()), ("APPROVED", [f"{self.pid}-blogger_en.json"]))


class NoAutomaticResendTest(SaveCase):
    def test_a_connection_that_never_opened_is_one_attempt_and_nothing_stays_behind(self):
        """BT-16 — 보내기 전 실패(이름 풀이·연결): 서버는 못 봤다. 다시 보내지 않고 저널을 지우며 글은 승인 상태 그대로다."""
        self.env.dial_error = OSError(101, "unreachable")
        dials = len(self.env.dials)
        with self.assertRaises(NetError) as caught:
            self.save(self.pid)
        self.assertEqual((caught.exception.code, caught.exception.outcome_unknown), ("NETWORK_OFFLINE", False))
        self.assertEqual((len(self.env.dials) - dials, self.google.requests, self.journals(), self.variant(self.pid).status), (1, [], [], "APPROVED"))

    def test_client_errors_are_not_resent_and_leave_no_journal(self):
        for reply, code in ((bs.google_error(403, "forbidden"), "BLOGGER_PERMISSION_DENIED"), (bs.google_error(404), "BLOGGER_NOT_FOUND"), (bs.google_error(400), "REQUEST_INVALID"),
                            (bs.google_error(403, "accessNotConfigured"), "BLOGGER_API_NOT_ENABLED"), (bs.google_error(429, "rateLimitExceeded"), "API_RATE_LIMITED"), (bs.google_error(403, "dailyLimitExceeded"), "API_RATE_LIMITED")):
            self.google.requests.clear()
            self.cool()
            self.advance(minutes=2)
            self.google.push("insert", reply)
            with self.subTest(code=code), self.assertRaises(NetError) as caught:
                self.save(self.pid)
            self.assertEqual(caught.exception.code, code)
            self.assertEqual((len(self.inserts()), self.journals(), self.variant(self.pid).status), (1, [], "APPROVED"), code)

    def test_a_401_refreshes_the_token_once_and_resends_once(self):
        """유일한 자동 재전송 — 401 은 처리되지 않은 요청이라 갱신해서 한 번만 다시 보낸다(글은 하나만 저장된다)."""
        self.google.access_tokens.clear()
        self.save(self.pid)
        self.assertEqual(self.google.summaries()[:3], [f"POST www.googleapis.com/blogger/v3/blogs/{fs.BLOG_EN}/posts?isDraft=true", "POST oauth2.googleapis.com/token",
                                                      f"POST www.googleapis.com/blogger/v3/blogs/{fs.BLOG_EN}/posts?isDraft=true"])
        self.assertEqual(len(self.stored()), 1)
        self.assertEqual(self.variant(self.pid).status, "DRAFT_SAVED")

    def test_two_401_answers_in_a_row_stop_with_no_third_try(self):
        second = self.approve("blogger_en", "둘째 글")
        self.google.push("insert", bs.google_error(401), bs.google_error(401))
        with self.assertRaises(NetError) as caught:
            self.save(second)
        self.assertEqual(caught.exception.code, "BLOGGER_AUTH_EXPIRED")
        self.assertEqual((len(self.inserts()), self.stored(), self.journals()), (2, [], []))

    def test_a_refused_refresh_token_stops_without_sending_the_post(self):
        flow.forget()
        self.google.refresh_tokens.clear()
        with self.assertRaises(NetError) as caught:
            self.save(self.pid)
        self.assertEqual(caught.exception.code, "BLOGGER_AUTH_EXPIRED")
        self.assertEqual((self.inserts(), self.journals(), self.variant(self.pid).status), ([], [], "APPROVED"))


class UnknownOutcomeTest(SaveCase):
    def test_a_connection_lost_after_the_server_stored_the_post_adopts_it_without_a_second_send(self):
        """BT-17·18·R4 — 보낸 뒤 끊겼는데 서버는 저장했다: 같은 제목의 초안을 먼저 찾아 정확히 하나면 이어받는다. 두 번째 보내기는 없다."""
        self.google.push("insert", bs.STORE_THEN_DISCONNECT)
        result = self.save(self.pid)
        self.assertTrue(result.adopted)
        self.assertEqual(len(self.inserts()), 1, "두 번째로 보내지 않았다")
        self.assertEqual(self.google.summaries()[0], f"POST www.googleapis.com/blogger/v3/blogs/{fs.BLOG_EN}/posts?isDraft=true")
        self.assertIn("/posts?status=DRAFT&orderBy=UPDATED&maxResults=5&fetchBodies=false&view=ADMIN", self.google.summaries()[1])
        self.assertEqual(len(self.stored()), 1)
        variant = self.variant(self.pid)
        self.assertEqual((variant.status, variant.remote_id), ("DRAFT_SAVED", self.stored()[0]["id"]))
        self.assertEqual(self.journals(), [])
        self.assertClean()

    def test_a_connection_lost_and_nothing_found_stops_and_the_next_press_checks_first_and_then_sends(self):
        """BT-17 — 서버가 못 받았거나 알 수 없으면 멈춘다(`BLOGGER_DRAFT_UNKNOWN`). 사용자가 다시 누르면 새로 보내기 전에 먼저 같은 제목을 찾고, 없을 때만 보낸다."""
        self.google.push("insert", bs.DISCONNECT)
        with self.assertRaises(AppError) as caught:
            self.save(self.pid)
        self.assertEqual(caught.exception.code, "BLOGGER_DRAFT_UNKNOWN")
        self.assertEqual((len(self.inserts()), self.journals(), self.variant(self.pid).status), (1, [f"{self.pid}-blogger_en.json"], "APPROVED"))
        record = json.loads((self.journal_dir() / f"{self.pid}-blogger_en.json").read_text(encoding="utf-8"))
        self.assertEqual(record["stage"], "unknown")
        self.google.requests.clear()
        self.cool()
        result = self.save(self.pid)
        self.assertEqual((result.adopted, len(self.inserts())), (False, 1), "찾아보고 없어서 새로 한 번 보냈다")
        self.assertIn("/posts?status=DRAFT", self.google.summaries()[0])
        self.assertTrue(any("이전에 보내다 멈춘 글" in note for note in result.notes), result.notes)
        self.assertEqual((len(self.stored()), self.journals()), (1, []))

    def test_a_5xx_after_sending_is_an_unknown_outcome_not_a_plain_failure(self):
        self.google.push("insert", bs.google_error(503))
        with self.assertRaises(AppError) as caught:
            self.save(self.pid)
        self.assertEqual(caught.exception.code, "BLOGGER_DRAFT_UNKNOWN")
        self.assertEqual(len(self.inserts()), 1)
        self.assertIn("확인 없이", caught.exception.rendered().action)

    def test_two_same_title_drafts_are_never_chosen_between(self):
        self.google.add_post(fs.BLOG_EN, fs.TITLE, updated=self.ctx.now())
        self.google.push("insert", bs.STORE_THEN_DISCONNECT)
        with self.assertRaises(AppError) as caught:
            self.save(self.pid)
        self.assertEqual(caught.exception.code, "BLOGGER_DRAFT_UNKNOWN")
        self.assertEqual((len(self.inserts()), len(self.stored()), self.variant(self.pid).status), (1, 2, "APPROVED"))
        self.google.requests.clear()
        self.cool()
        with self.assertRaises(AppError) as caught:
            self.save(self.pid)
        self.assertEqual((caught.exception.code, self.inserts()), ("BLOGGER_DRAFT_UNKNOWN", []), "다시 눌러도 둘이 있으면 새로 보내지 않는다")

    def test_the_time_window_for_a_same_title_draft_is_five_minutes_before_and_fifteen_after(self):
        """BT-18 — 저널 시각 앞 5분(시계 차이)·뒤 15분 안에 고쳐진 같은 제목만 이어받는다. 밖이면 다른 글이다."""
        from datetime import timedelta
        now = self.ctx.now()
        for label, offset, adopted in (("정각", timedelta(0), True), ("5분 전", timedelta(minutes=-5), True), ("15분 뒤", timedelta(minutes=15), True), ("6분 전", timedelta(minutes=-6), False), ("16분 뒤", timedelta(minutes=16), False)):
            pid = self.approve("blogger_en", "시간 시험 " + label)
            self.google.add_post(fs.BLOG_EN, "시간 시험 " + label, updated=now + offset)
            record = flow.JournalRecord(pid, "blogger_en", flow._sha("시간 시험 " + label), "0" * 64, "sending", self.ctx.stamp())
            flow.BloggerJournal(self.journal_dir()).write(record)
            self.google.requests.clear()
            self.cool()
            self.advance(minutes=2)
            now = self.ctx.now()
            result = self.save(pid)
            self.assertEqual(result.adopted, adopted, label)
            self.assertEqual(len(self.inserts()), 0 if adopted else 1, label)

    def test_a_different_title_or_a_published_post_is_never_adopted(self):
        self.google.add_post(fs.BLOG_EN, fs.TITLE + " 다름", updated=self.ctx.now())
        self.google.add_post(fs.BLOG_EN, fs.TITLE, status="LIVE", updated=self.ctx.now())
        flow.BloggerJournal(self.journal_dir()).write(flow.JournalRecord(self.pid, "blogger_en", flow._sha(fs.TITLE), "0" * 64, "sending", self.ctx.stamp()))
        result = self.save(self.pid)
        self.assertEqual((result.adopted, len(self.inserts())), (False, 1))

    def test_a_journal_left_by_a_crashed_run_is_checked_before_anything_new_is_sent(self):
        """앱 종료 중 전송 — 저널 `sending` 이 남은 채 다시 실행하면 새로 보내기 전에 먼저 찾는다."""
        self.google.add_post(fs.BLOG_EN, fs.TITLE, updated=self.ctx.now())
        flow.BloggerJournal(self.journal_dir()).write(flow.JournalRecord(self.pid, "blogger_en", flow._sha(fs.TITLE), "0" * 64, "sending", self.ctx.stamp()))
        result = self.save(self.pid)
        self.assertEqual((result.adopted, self.inserts(), len(self.stored())), (True, [], 1))
        self.assertTrue(any("이전에 보내다 멈춘 글" in note for note in result.notes))
        self.assertEqual((self.journals(), self.variant(self.pid).status), ([], "DRAFT_SAVED"))

    def test_when_the_state_cannot_be_saved_after_the_insert_the_journal_stays_and_the_next_press_adopts(self):
        real = Store.save
        calls = []

        def failing(store, project):
            calls.append(project.variant("blogger_en").status)
            if project.variant("blogger_en").status == "DRAFT_SAVED":
                raise AppError("FILE_WRITE_FAILED", {"경로": "시험"}, detail="시험용 실패")
            return real(store, project)

        with mock.patch.object(Store, "save", failing), self.assertRaises(AppError) as caught:
            self.save(self.pid)
        self.assertEqual(caught.exception.code, "FILE_WRITE_FAILED")
        self.assertEqual((self.variant(self.pid).status, len(self.stored()), self.journals()), ("APPROVED", 1, [f"{self.pid}-blogger_en.json"]))
        record = json.loads((self.journal_dir() / f"{self.pid}-blogger_en.json").read_text(encoding="utf-8"))
        self.assertEqual(record["stage"], "unknown")
        self.google.requests.clear()
        self.cool()
        result = self.save(self.pid)
        self.assertEqual((result.adopted, self.inserts(), self.variant(self.pid).status), (True, [], "DRAFT_SAVED"))
        self.assertEqual(len(self.stored()), 1, "초안은 하나뿐이다")

    def test_a_find_request_that_fails_after_an_unknown_send_still_stops_with_unknown(self):
        self.google.push("insert", bs.DISCONNECT)
        self.google.push("list", bs.google_error(500))
        with self.assertRaises(AppError) as caught:
            self.save(self.pid)
        self.assertEqual((caught.exception.code, len(self.inserts())), ("BLOGGER_DRAFT_UNKNOWN", 1))


class JournalAndLockTest(SaveCase):
    def test_the_journal_is_written_before_the_send_and_holds_only_hashes_a_stage_and_a_time(self):
        seen = []
        real = flow.BloggerJournal.write

        def spy(journal, record):
            real(journal, record)
            seen.append((record.stage, sorted(path.name for path in self.journal_dir().glob("*.json")), len(self.inserts())))

        with mock.patch.object(flow.BloggerJournal, "write", spy):
            self.save(self.pid)
        self.assertEqual(seen, [("sending", [f"{self.pid}-blogger_en.json"], 0)], "보내기 전에 저널이 있었다")
        self.google.push("insert", bs.DISCONNECT)
        second = self.approve("blogger_en", "둘째 글")
        with self.assertRaises(AppError):
            self.save(second)
        text = (self.journal_dir() / f"{second}-blogger_en.json").read_text(encoding="utf-8")
        data = json.loads(text)
        self.assertEqual(sorted(data), ["content_sha256", "project_id", "schema", "slot", "stage", "started_at", "title_sha256"])
        self.assertRegex(data["title_sha256"], r"^[0-9a-f]{64}$")
        for secret in ("둘째 글", fs.BLOG_EN, "CANARY_", "ya29", "1//0", "에너지"):
            self.assertNotIn(secret, text)

    def test_when_the_journal_cannot_be_written_nothing_is_sent(self):
        with mock.patch.object(flow.BloggerJournal, "write", side_effect=AppError("FILE_WRITE_FAILED", {"경로": "시험"}, detail="시험용 실패")), self.assertRaises(AppError) as caught:
            self.save(self.pid)
        self.assertEqual((caught.exception.code, self.inserts()), ("FILE_WRITE_FAILED", []))
        self.assertEqual(self.variant(self.pid).status, "APPROVED")

    def test_a_broken_journal_is_not_read_and_nothing_is_sent(self):
        self.journal_dir().mkdir(parents=True, exist_ok=True)
        (self.journal_dir() / f"{self.pid}-blogger_en.json").write_text('{"schema": 1, "x": 1}', encoding="utf-8")
        with self.assertRaises(AppError) as caught:
            self.save(self.pid)
        self.assertEqual((caught.exception.code, self.inserts()), ("SETTINGS_INVALID", []))

    def test_a_second_press_for_the_same_post_and_slot_while_one_runs_is_refused(self):
        """B-10 — 같은 글·같은 슬롯의 진행 중인 두 번째 요청은 거절한다. 다른 슬롯은 막지 않는다."""
        with flow._slot_lock(self.ctx, self.pid, "blogger_en"):
            with self.assertRaises(AppError) as caught:
                self.save(self.pid)
            self.assertEqual(caught.exception.code, "PUBLISH_IN_PROGRESS")
            self.assertEqual((self.google.requests, self.journals()), ([], []))
            with flow._slot_lock(self.ctx, self.pid, "blogger_ko"):
                pass
        self.save(self.pid)
        self.assertEqual(len(self.stored()), 1)

    def test_the_limit_is_checked_before_sending_and_leaves_no_journal(self):
        self.exhaust(self.entry("blogger_en"))
        with self.assertRaises(AppError) as caught:
            self.save(self.pid)
        self.assertEqual(caught.exception.code, "API_RATE_LIMITED")
        self.assertEqual((self.google.requests, self.journals(), self.variant(self.pid).status), ([], [], "APPROVED"))

    def exhaust(self, entry):
        from chanceblog_desktop.service import quota
        guard = quota.QuotaGuard(self.ctx)
        used = 0
        while True:
            if used % 5 == 0:
                self.advance(minutes=2)
            if not hasattr(guard.acquire_entry(entry, calls=1, priority=quota.CRITICAL, kind="blogger_fill"), "entry_id"):
                return
            used += 1


class SwitchesTest(SaveCase):
    def test_the_write_needs_all_three_switches(self):
        for patches, code in (({"EXTERNAL_WRITE": False}, "EXTERNAL_WRITE_DISABLED"), ({"NET_BLOGGER_DRAFT": False}, "NETWORK_DISABLED"), ({"NET_BLOGGER_OAUTH": False}, "NETWORK_DISABLED")):
            with mock.patch.multiple(capabilities, **patches), self.assertRaises(AppError) as caught:
                self.save(self.pid)
            self.assertEqual(caught.exception.code, code, patches)
        self.assertNothingSent()

    def test_a_full_fake_run_login_save_check_disconnect_touches_only_fakes_and_loopback(self):
        """BT-83 — 로그인 → 연결 확인 → 초안 저장 → 연결 해제 한 바퀴가 가짜와 루프백에만 닿는다."""
        self.login("blogger_ko")
        korean = self.approve("blogger_ko", "한글 글")
        flow.check(self.ctx, "blogger_ko", confirmed=True)
        self.save(korean, "blogger_ko")
        self.assertEqual(self.variant(korean, "blogger_ko").status, "DRAFT_SAVED")
        result = flow.disconnect(self.ctx, "blogger_ko", confirmed=True)
        self.assertTrue(result.revoked)
        self.assertEqual(flow.status(self.ctx, "blogger_ko").state, "login_needed")
        shapes = [self.google.shape_of(request) for request in self.google.requests]
        self.assertTrue(all(shape is not None for shape in shapes))
        self.assertClean()


if __name__ == "__main__":
    unittest.main()
