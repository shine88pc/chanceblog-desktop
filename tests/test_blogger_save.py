"""Blogger 초안 저장(`service/blogger_flow.py::save_draft`) 시험 — BLOGGER 설계서 BT-10·14·16–18·32·50–56 의 흐름 쪽과 7절 '탐침' 표(초안 전용·재시도·중복·로컬 이미지·HTML)(결정 D-774).

진짜 접속 틀 + **요청 모양을 엄격히 검사하는 가짜 구글**(`FakeGoogle`) + 가짜 보관소·가짜 브라우저. 소켓은 루프백 말고는 열리지 않는다(감시가 센다). 지키는 것:
  1) 확인 없이는 아무것도 하지 않고, 승인한 현재 판의 글만 보낸다 · 막힌 글(키 모양·이 PC 경로·위험한 표기·이 PC 의 사진)은 한 건도 보내지 않는다.
  2) 쓰기는 요청 한 건이다: 보내기 전 실패·4xx 는 다시 보내지 않고, 보낸 뒤 끊기거나 5xx 면 **같은 제목의 초안을 먼저 찾아** 정확히 하나일 때만 이어받고 아니면 멈춘다(중복 초안 없음). 401 뒤 갱신해 한 번 다시 보내는 것이 유일한 예외다.
  3) 공개(LIVE) 같은 초안이 아닌 답은 즉시 멈추고 글 상태는 실패로 바뀐다 · 저널은 보내기 전에 쓰고 해시뿐이다 · 한도는 항목마다.
  4) 재작업 1 권고-1 — 보내기 직전 검사는 두 눈이다: 본문 속 비밀 형태 검사기와 올리기 직전 마지막 관문(`pages.secret_labels`)의 합집합 — 한쪽만 보면 놓치던 모양(눈에 안 보이는 글자가 낀 토큰·Slack·Anthropic 따위)도 보내기 전에 막힌다.
  5) 재작업 1 권고-2 — 이어받기는 저널이 가리키는 글이 **지금 승인한 글**(제목·내용 해시가 같다)일 때만 한다: 원고를 고쳐 다시 승인한 글은 옛 초안을 이어받지 않고 새로 보낸다(옛 초안은 지우지도 덮어쓰지도 않는다).
  6) 재작업 1 시험 렌즈 Q 권고 R2–R4 — 저널 파일 길 막이(`../`·`a/b`·65자 따위는 어느 길로도 파일을 건드리지 못한다)와 지우기 실패 알림 · 구글 429 뒤의 쉼 · 사용량 기록 잠김·못 읽음의 오류 이름(`KEYS_BUSY`·`QUOTA_STATE_INVALID`) · 승인 상태인데 렌더링이 낡은 글의 가드.
"""
import dataclasses
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
from chanceblog_desktop.service import connections as cn  # noqa: E402
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


class HandEdited:
    """읽어 온 프로젝트를 감싸 '승인했다는 상태는 그대로인데 렌더링이 지금 원고와 맞지 않는' 프로젝트를 흉내 낸다(재작업 1 — 시험 렌즈 Q R4). 정상 길로는 그런 프로젝트가 읽히지 않는다 —
    불러오기 검사(`ContentProject`)가 승인 상태의 렌더 판 번호가 다르면 거절한다 — 그래서 불러오는 길(`Store.load`)을 바꿔야 보내는 쪽의 겹쳐 둔 가드에 닿는다."""

    def __init__(self, project, *, newer_revision=False, empty_render=False):
        self._project = project
        self._empty_render = empty_render
        self.revision = project.revision + (1 if newer_revision else 0)

    def variant(self, slot):
        variant = self._project.variant(slot)
        return dataclasses.replace(variant, rendered="") if self._empty_render else variant

    def __getattr__(self, name):
        return getattr(self._project, name)


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

    def test_an_approved_post_whose_render_is_not_the_current_text_is_never_sent_even_if_the_state_still_says_approved(self):
        """재작업 1 시험 렌즈 Q 권고 R4 — 두 번째 가드(`rendered_revision != revision`·빈 렌더링)를 직접 본다. 위 시험의 '승인 뒤 원고를 고침' 은 상태가 '렌더링 만듦' 으로 돌아가 앞 줄에서 걸려 이 가드에 닿지 않는다.
        그래서 불러오는 길을 바꿔 닿게 한다 — 겹쳐 둔 방어가 그대로 살아 있는지 본다. 한 건도 보내지 않고 저널도 없고 상태는 승인 그대로다."""
        real = Store.load
        cases = (("렌더링이 옛 판", lambda project: HandEdited(project, newer_revision=True)), ("렌더링이 빔", lambda project: HandEdited(project, empty_render=True)))
        for label, wrap in cases:
            with self.subTest(case=label), mock.patch.object(Store, "load", lambda store, project_id, wrap=wrap: wrap(real(store, project_id))), self.assertRaises(AppError) as caught:
                self.save(self.pid)
            self.assertEqual(caught.exception.code, "STATUS_TRANSITION_INVALID", label)
            self.assertIn("렌더링", str(caught.exception.detail), label)
            self.assertNothingSent()
        self.save(self.pid)                                                          # 가드가 글을 상하게 하지 않았다 — 정상 길로는 그대로 저장된다
        self.assertEqual(self.variant(self.pid).status, "DRAFT_SAVED")

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

    def test_after_a_429_the_item_rests_and_the_next_press_asks_google_nothing_until_the_rest_is_over(self):
        """재작업 1 시험 렌즈 Q 권고 R3 — 구글이 429 로 답하면 한도 저장소에 '쉬어라' 가 적힌다(`API_RATE_LIMITED` → `quota.RATE_LIMITED`): 곧바로 다시 눌러도 구글에는 요청이 한 건도 가지 않고 쉬는 시각이 알림에 있다.
        쉬는 시간이 지나면 다시 된다. (위 시험은 사례마다 `cool()` 로 쉼을 지워서 이 줄이 묶이지 않았다 — 429 를 다른 오류로 적으면 429 뒤에도 곧바로 구글을 두드린다.)"""
        self.google.push("insert", bs.google_error(429, "rateLimitExceeded"))
        with self.assertRaises(NetError) as first:
            self.save(self.pid)
        self.assertEqual((first.exception.code, len(self.inserts()), self.journals()), ("API_RATE_LIMITED", 1, []))
        self.google.requests.clear()
        with self.assertRaises(AppError) as second:
            self.save(self.pid)
        self.assertEqual(second.exception.code, "API_RATE_LIMITED")
        self.assertTrue(second.exception.slots.get("재시도 가능 시각"), "쉬는 시각을 알린다")
        self.assertIn("한국 시간", second.exception.rendered().message)
        self.assertEqual((self.google.requests, self.journals(), self.variant(self.pid).status), ([], [], "APPROVED"))
        self.advance(minutes=2)                                                      # 쉬는 시간(처음 429 는 5초)이 지났다
        self.save(self.pid)
        self.assertEqual((len(self.inserts()), len(self.stored()), self.variant(self.pid).status), (1, 1, "DRAFT_SAVED"))

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
            record = flow.JournalRecord(pid, "blogger_en", flow._sha("시간 시험 " + label), self.post_hash(pid), "sending", self.ctx.stamp())
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
        flow.BloggerJournal(self.journal_dir()).write(flow.JournalRecord(self.pid, "blogger_en", flow._sha(fs.TITLE), self.post_hash(self.pid), "sending", self.ctx.stamp()))
        result = self.save(self.pid)
        self.assertEqual((result.adopted, len(self.inserts())), (False, 1))

    def test_a_journal_left_by_a_crashed_run_is_checked_before_anything_new_is_sent(self):
        """앱 종료 중 전송 — 저널 `sending` 이 남은 채 다시 실행하면 새로 보내기 전에 먼저 찾는다."""
        self.google.add_post(fs.BLOG_EN, fs.TITLE, updated=self.ctx.now())
        flow.BloggerJournal(self.journal_dir()).write(flow.JournalRecord(self.pid, "blogger_en", flow._sha(fs.TITLE), self.post_hash(self.pid), "sending", self.ctx.stamp()))
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


class StaleJournalTest(SaveCase):
    """재작업 1 권고-2 — 안전 검증 S 의 탐침 p5b: 보내다 끊겨 서버에 판 A 가 저장된 채 사람이 원고를 판 B 로 고쳐 다시 승인하고 '초안 저장' 을 누르면 옛 판 A 를 이어받아 '저장됨'(`adopted·verified`)으로 적었다.
    저널에는 제목·내용의 해시가 있으니 지금 글과 견주어 다르면 이어받지 않고 새로 보낸다 — 옛 초안은 지우지도 덮어쓰지도 않는다(Blogger 의 글은 사람이 정리한다)."""

    FIRST = "## 소제목\n\n에너지를 아끼는 작은 습관은 매일 조금씩 실천할 때 가장 오래 갑니다. 이 글은 첫째 판본입니다.\n\n둘째 문단입니다.\n"
    SECOND = "## 소제목\n\n전혀 다른 내용으로 고쳐 쓴 둘째 판본입니다. 이전 글의 문장은 하나도 남기지 않았어요.\n\n마지막 문단입니다.\n"

    def first_attempt_that_ends_unknown(self, pid):
        """서버는 저장했는데 답이 끊기고 같은 제목 찾기도 실패한다 — 서버에 초안 하나(판 A)가 있고 저널이 `unknown` 으로 남는다. 그 초안의 번호를 돌려준다."""
        self.google.push("insert", bs.STORE_THEN_DISCONNECT)
        self.google.push("list", bs.google_error(503))
        with self.assertRaises(AppError) as caught:
            self.save(pid)
        self.assertEqual(caught.exception.code, "BLOGGER_DRAFT_UNKNOWN")
        self.assertEqual((len(self.stored()), self.journals()), (1, [f"{pid}-blogger_en.json"]))
        return self.stored()[0]["id"]

    def second_press(self, pid):
        self.advance(minutes=1)
        self.cool()
        self.google.requests.clear()
        return self.save(pid)

    def test_an_edited_post_does_not_adopt_the_old_draft_and_a_new_one_is_made_beside_it(self):
        pid = self.approve("blogger_en", markdown=self.FIRST)
        old_id = self.first_attempt_that_ends_unknown(pid)
        old_content = self.stored()[0]["content"]
        self.reapprove(pid, markdown=self.SECOND)
        result = self.second_press(pid)
        self.assertFalse(result.adopted)
        self.assertNotEqual(result.post_id, old_id)
        self.assertEqual(self.google.summaries()[0], f"POST www.googleapis.com/blogger/v3/blogs/{fs.BLOG_EN}/posts?isDraft=true")
        self.assertEqual((len(self.inserts()), self.google.count("?status=DRAFT")), (1, 0), "새로 한 번 보냈고 옛 글 때문에 같은 제목 찾기를 하지도 않았다")
        drafts = {draft["id"]: draft for draft in self.stored()}
        self.assertEqual(sorted(drafts), sorted([old_id, result.post_id]), "옛 초안은 그대로 있고 새 초안이 하나 더 생겼다")
        self.assertEqual(drafts[old_id]["content"], old_content, "옛 초안은 지우지도 덮어쓰지도 않았다")
        self.assertIn("둘째 판본", drafts[result.post_id]["content"])
        self.assertNotIn("첫째 판본", drafts[result.post_id]["content"])
        self.assertTrue(any("내용이 달라서 이어받지 않고" in note for note in result.notes), result.notes)
        variant = self.variant(pid)
        self.assertEqual((variant.status, variant.remote_id), ("DRAFT_SAVED", result.post_id), "저장됨으로 적히는 번호는 지금 글의 초안이다")
        self.assertEqual(self.journals(), [])
        self.assertClean()

    def test_an_edited_title_does_not_adopt_the_old_draft_either(self):
        pid = self.approve("blogger_en", "첫째 제목", markdown=self.FIRST)
        old_id = self.first_attempt_that_ends_unknown(pid)
        self.reapprove(pid, title="고쳐 쓴 둘째 제목")
        result = self.second_press(pid)
        self.assertEqual((result.adopted, len(self.inserts()), result.post_id == old_id), (False, 1, False))
        self.assertEqual(sorted(draft["title"] for draft in self.stored()), ["고쳐 쓴 둘째 제목", "첫째 제목"])
        self.assertTrue(any("내용이 달라서 이어받지 않고" in note for note in result.notes), result.notes)

    def test_the_same_post_is_adopted_on_the_next_press_and_nothing_is_sent_again(self):
        pid = self.approve("blogger_en", markdown=self.FIRST)
        old_id = self.first_attempt_that_ends_unknown(pid)
        result = self.second_press(pid)
        self.assertEqual((result.adopted, result.verified, result.post_id), (True, True, old_id))
        self.assertEqual((self.inserts(), len(self.stored()), self.journals()), ([], 1, []))
        self.assertFalse(any("내용이 달라서" in note for note in result.notes))
        self.assertEqual(self.variant(pid).remote_id, old_id)

    def test_what_counts_is_the_text_not_the_revision_so_an_edit_undone_is_the_same_post_again(self):
        """원고를 고쳤다가 되돌려 승인하면 판 번호는 올랐어도 글은 같다 — 저널의 해시가 같으니 옛 초안을 이어받는다."""
        pid = self.approve("blogger_en", markdown=self.FIRST)
        old_id = self.first_attempt_that_ends_unknown(pid)
        self.reapprove(pid, markdown=self.SECOND)
        self.reapprove(pid, markdown=self.FIRST)
        result = self.second_press(pid)
        self.assertEqual((result.adopted, result.post_id, self.inserts()), (True, old_id, []))

    def test_a_stale_journal_of_any_stage_is_replaced_by_the_new_send_and_the_next_press_follows_the_new_one(self):
        """옛 저널(`sending`)이 남은 채 글을 고쳐 보내면 새 저널이 옛 저널을 덮고, 그 보냄이 또 끊겨도 다음 누름은 새 글의 저널을 따른다."""
        pid = self.approve("blogger_en", markdown=self.FIRST)
        flow.BloggerJournal(self.journal_dir()).write(flow.JournalRecord(pid, "blogger_en", flow._sha(fs.TITLE), self.post_hash(pid), "sending", self.ctx.stamp()))
        self.reapprove(pid, markdown=self.SECOND)
        self.google.push("insert", bs.DISCONNECT)
        self.google.push("list", bs.google_error(503))
        with self.assertRaises(AppError) as caught:
            self.save(pid)
        self.assertEqual(caught.exception.code, "BLOGGER_DRAFT_UNKNOWN")
        record = flow.BloggerJournal(self.journal_dir()).read(pid, "blogger_en")
        self.assertEqual((record.stage, record.content_sha256 == self.post_hash(pid)), ("unknown", True), "저널은 지금 글의 해시를 가리킨다")
        self.assertEqual(len(self.inserts()), 1)

    def test_the_journal_matches_only_when_both_hashes_are_equal(self):
        from chanceblog_desktop.render.blogger import BloggerPost
        post = BloggerPost("제목", "<p>본문</p>", ())
        same = flow.JournalRecord("p1", "blogger_en", flow._sha("제목"), flow._sha("<p>본문</p>"), "sending", "2026-11-26T00:00:00Z")
        self.assertTrue(flow._is_this_post(same, post))
        for label, record in (("제목 해시가 다름", flow.JournalRecord("p1", "blogger_en", flow._sha("다른 제목"), flow._sha("<p>본문</p>"), "sending", "2026-11-26T00:00:00Z")),
                              ("내용 해시가 다름", flow.JournalRecord("p1", "blogger_en", flow._sha("제목"), flow._sha("<p>다른 본문</p>"), "unknown", "2026-11-26T00:00:00Z")),
                              ("둘 다 다름", flow.JournalRecord("p1", "blogger_en", "0" * 64, "1" * 64, "sending", "2026-11-26T00:00:00Z"))):
            with self.subTest(label=label):
                self.assertFalse(flow._is_this_post(record, post))


def secret_samples():
    """한쪽 눈만으로는 놓치던 모양들(안전 검증 S 의 탐침 p4 — 열셋) — 가짜 값은 모두 **실행 때 조립**한다(소스에는 키 모양이 한 덩어리로 없다)."""
    zero_width, soft_hyphen, word_joiner, bom = chr(0x200B), chr(0x00AD), chr(0x2060), chr(0xFEFF)
    body = "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
    google_tail = "SyA1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q"
    return {
        "GitHub 토큰 접두사 안에 폭 없는 공백": "gh" + zero_width + "p_" + body,
        "GitHub 토큰 몸통 가운데 폭 없는 공백": "ghp_" + body[:10] + zero_width + body[10:],
        "GitHub 토큰 안에 소프트 하이픈": "gh" + soft_hyphen + "p_" + body,
        "GitHub 토큰 안에 단어 이음표": "ghp" + word_joiner + "_" + body,
        "GitHub 토큰 안에 BOM": "gh" + bom + "p_" + body,
        "Google API 키 안에 폭 없는 공백": "AI" + zero_width + "za" + google_tail,
        "Slack 봇 토큰": "xox" + "b-" + "1234567890-1234567890123-" + "a" * 24,
        "Slack 웹훅 주소": "https" + "://hooks." + "slack.com/services/" + "T00000000/B00000000/" + "X" * 24,
        "OpenAI 프로젝트 키": "sk-" + "proj-" + "a" * 40,
        "Anthropic 키": "sk-" + "ant-api03-" + "a" * 40,
        "npm 토큰": "npm_" + "a" * 36,
        "Telegram 봇 토큰": "123456789:" + "AA" + "a" * 33,
        "글자에 바로 붙은 Google API 키": "abc" + "AI" + "za" + google_tail,
    }


def ordinary_texts():
    """평범한 글 — 두 눈이 모두 지나가게 두어야 한다(거짓 경보 점검): 한글·영문 문장·사진 주소·커밋 해시·UUID·'token' 같은 낱말."""
    return {"한글 문장": "에너지를 아끼는 작은 습관은 매일 조금씩 실천할 때 가장 오래 갑니다.", "영문 문장": "Small habits that save energy add up when you repeat them every day.",
            "사진 주소": "https://images.unsplash.com/photo-1500000000000-aaaaaaaaaaaa?w=1200", "커밋 해시": "commit " + "0123456789abcdef" * 2 + "01234567",
            "UUID": "id 123e4567-e89b-12d3-a456-426614174000", "token 이라는 낱말": "the token of appreciation and the key to a good habit", "하이픈 낱말": "task-oriented sk-ills and ghp stands for nothing here",
            "숫자와 콜론": "회의는 12:30 이고 전화는 010-1234-5678 입니다"}


class BothSecretEyesTest(unittest.TestCase):
    """재작업 1 권고-1 — 보내기 직전 검사(`check_post`)는 본문 속 비밀 형태 검사기와 올리기 직전 마지막 관문(`pages.secret_labels`)의 합집합이다(설계 H8·3.7 ③).
    예전에는 앞의 눈만 보아 표본 31개 가운데 13개가 이 길을 지났다 — 승인 관문이 대부분 먼저 막지만 보낼 때 따로 입력하는 라벨·저장소 파일을 직접 고친 글·승인한 글과 다른 글은 그 관문을 거치지 않는다."""

    def check(self, title="안전한 제목", html="<p>안전한 본문입니다.</p>", labels=()):
        from types import SimpleNamespace
        from chanceblog_desktop.render.blogger import BloggerPost
        project = SimpleNamespace(source_content="안전한 본문입니다.", title=title, references=(), assets=())
        flow.check_post(BloggerPost(title, html, tuple(labels)), project, ())

    def refused_code(self, **fields):
        with self.assertRaises(AppError) as caught:
            self.check(**fields)
        return caught.exception.code

    def test_every_sample_one_eye_alone_used_to_miss_is_refused_before_any_request(self):
        from chanceblog_desktop.publish import pages
        for label, text in secret_samples().items():
            with self.subTest(label=label):
                self.assertTrue(pages.secret_labels(text), f"{label}: 올리기 직전 마지막 관문이 이 표본을 알아보지 못한다 — 시험이 헛돈다")
                self.assertIn(self.refused_code(html="<p>" + text + "</p>"), ("SECRET_SHAPE_FOUND", "SECRET_IN_TEXT_BLOCKED"), label)

    def test_a_shape_that_only_the_last_gate_knows_is_refused_with_the_designed_code_and_names_no_value(self):
        text = secret_samples()["Slack 봇 토큰"]
        with self.assertRaises(AppError) as caught:
            self.check(html="<p>" + text + "</p>")
        error = caught.exception
        self.assertEqual(error.code, "SECRET_IN_TEXT_BLOCKED")
        shown = error.rendered()
        for hidden in (text, text[:12], text[-10:]):
            self.assertNotIn(hidden, shown.message + shown.action + str(error.detail) + repr(error.slots) + "".join(getattr(error, "notes", ())))

    def test_the_first_eye_still_answers_first_for_what_it_knows(self):
        self.assertEqual(self.refused_code(html="<p>" + "AI" + "za" + "A" * 35 + "</p>"), "SECRET_SHAPE_FOUND")

    def test_a_sample_is_refused_in_the_title_in_the_html_and_in_a_label_alike(self):
        for name in ("Slack 봇 토큰", "npm 토큰", "GitHub 토큰 안에 소프트 하이픈"):
            text = secret_samples()[name]
            for where, fields in (("제목", dict(title="제목 " + text)), ("본문", dict(html="<p>" + text + "</p>")), ("라벨", dict(labels=("에너지", text)))):
                with self.subTest(sample=name, where=where):
                    self.assertIn(self.refused_code(**fields), ("SECRET_SHAPE_FOUND", "SECRET_IN_TEXT_BLOCKED"))

    def test_ordinary_texts_pass_both_eyes(self):
        for label, text in ordinary_texts().items():
            with self.subTest(label=label):
                self.check(title="평범한 제목 " + label, html="<p>" + text + "</p>", labels=("에너지", "생활 습관"))

    def test_the_gate_calls_the_shared_last_gate_and_never_changes_it(self):
        """공용 함수는 부르기만 한다 — `check_post` 가 `pages.secret_labels` 를 제목·본문·라벨 세 글에 부른다."""
        seen = []
        real = flow.pages.secret_labels

        def spy(text):
            seen.append(text)
            return real(text)

        with mock.patch.object(flow.pages, "secret_labels", spy):
            self.check(title="제목 가", html="<p>본문 나</p>", labels=("라벨 다", "라벨 라"))
        self.assertEqual(seen, ["제목 가", "<p>본문 나</p>", "라벨 다, 라벨 라"])


class SecretEyesEndToEndTest(SaveCase):
    def test_a_token_the_first_eye_misses_in_the_text_stops_the_save_and_nothing_is_sent(self):
        token = secret_samples()["Slack 봇 토큰"]
        pid = self.approve("blogger_en", "토큰 든 글")
        self.poison(pid, fs.BODY_MARKDOWN + f"\n\n여기에 {token} 를 붙였어요.\n")
        with self.assertRaises(AppError) as caught:
            self.save(pid)
        self.assertEqual(caught.exception.code, "SECRET_IN_TEXT_BLOCKED")
        shown = caught.exception.rendered()
        for hidden in (token, token[:12]):
            self.assertNotIn(hidden, shown.message + shown.action + str(caught.exception.detail) + repr(caught.exception.slots))
        self.assertEqual((self.google.requests, self.journals(), self.variant(pid).status), ([], [], "APPROVED"))

    def test_a_token_typed_as_a_label_at_send_time_is_stopped_too_because_no_approval_looked_at_it(self):
        """`--tags` 는 승인할 때 검사되지 않는 입력이다 — 첫 번째 눈이 모르는 모양을 라벨에 넣어도 보내기 직전에 막힌다."""
        token = secret_samples()["npm 토큰"]
        with self.assertRaises(AppError) as caught:
            self.save(self.pid, tags=("에너지", token))
        self.assertEqual(caught.exception.code, "SECRET_IN_TEXT_BLOCKED")
        self.assertEqual((self.google.requests, self.journals(), self.variant(self.pid).status), ([], [], "APPROVED"))


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

    def test_a_usage_record_that_is_busy_or_cannot_be_read_stops_the_save_before_any_request_with_its_own_error(self):
        """재작업 1 시험 렌즈 Q 권고 R3 — 사용량 기록을 못 잡으면(다른 창이 쓰는 중 / 읽거나 쓰지 못함) 구글에 한 건도 보내지 않고 **각자의 오류 이름**으로 멈춘다: `KEYS_BUSY`·`QUOTA_STATE_INVALID`.
        둘 다 `API_RATE_LIMITED`(한도를 다 씀)로 뭉개 말하면 사람이 '내일 다시' 로 오해한다. 저널은 남지 않고 글은 승인 상태 그대로이며, 풀리면 같은 글이 그대로 저장된다."""
        real = cn.locked

        def broken(failure):
            def locked(ctx, name="connections", *, wait=cn.KEYS_LOCK_WAIT):
                if name == "quota-state":
                    raise failure
                return real(ctx, name, wait=wait)
            return locked

        for failure, code in ((AppError("KEYS_BUSY"), "KEYS_BUSY"), (AppError("FILE_WRITE_FAILED", {"경로": "시험"}, detail="시험용 실패"), "QUOTA_STATE_INVALID")):
            with self.subTest(code=code), mock.patch.object(cn, "locked", broken(failure)), self.assertRaises(AppError) as caught:
                self.save(self.pid)
            self.assertEqual(caught.exception.code, code)
            self.assertEqual((self.google.requests, self.journals(), self.variant(self.pid).status), ([], [], "APPROVED"), code)
        self.save(self.pid)
        self.assertEqual(self.variant(self.pid).status, "DRAFT_SAVED")

    def test_the_journal_file_name_comes_only_from_a_plain_post_number_and_a_known_slot(self):
        """재작업 1 시험 렌즈 Q 권고 R2 — 저널 파일 길 막이: 글 번호는 영문·숫자·`-`·`_` 1–64자 **통째**(`fullmatch`)이고 구분은 아는 둘뿐이다. `../`·`a/b`·`a` 역슬래시 `b`·공백·65자·빈 글·줄바꿈·NUL·모르는 구분은
        읽기·쓰기·지우기 어느 길로도 파일을 건드리지 못한다 — 폴더 밖의 표식 파일이 그대로 있고 새 파일이 생기지 않는다(이 갈래가 새로 연 '파일 하나 지우기' 의 근거 — `test_service_safety` 의 허용 한 줄이 가리키는 동작 시험)."""
        folder = self.journal_dir()
        (folder / "a").mkdir(parents=True, exist_ok=True)                            # `a/../../x` 를 운영체제가 실제로 풀 수 있게 — 없는 폴더를 지나는 `..` 는 윈도 밖에서는 풀리지 않는다
        marker = folder.parent / "x-blogger_en.json"
        marker.write_text("표식", encoding="utf-8")
        journal = flow.BloggerJournal(folder)
        record = flow.JournalRecord(self.pid, "blogger_en", "a" * 64, "b" * 64, "sending", self.ctx.stamp())

        def write(project_id, slot):
            return journal.write(dataclasses.replace(record, project_id=project_id, slot=slot))

        for good in (self.pid, "a" * 64, "Ab_9-z"):                                  # 멀쩡한 번호는 막지 않는다(전부 막는 길 막이가 아니다)
            for slot in ("blogger_en", "blogger_ko"):
                write(good, slot)
                self.assertEqual((journal.read(good, slot).project_id, journal.remove(good, slot), journal.read(good, slot)), (good, str(), None))
        self.assertEqual(journal.remove(self.pid, "blogger_en"), str(), "원래 없던 파일을 지우는 것은 알릴 일이 아니다")
        before = sorted(path.relative_to(self.tmp).as_posix() for path in self.tmp.rglob("*") if path.is_file())
        bad_ids = ("a/../../x", "../x", "..", "a/b", "a" + chr(92) + "b", "a b", "x" * 65, "", "a\n", "a\x00b", "한글", None, 5)
        bad_slots = ("", "blogger", "BLOGGER_EN", "blogger_en/../x", "blogger_en ", "일본어", None)
        for project_id, slot in [(item, "blogger_en") for item in bad_ids] + [(self.pid, item) for item in bad_slots]:
            for name, action in (("read", journal.read), ("remove", journal.remove), ("write", write)):
                with self.subTest(project_id=repr(project_id)[:20], slot=repr(slot)[:20], action=name), self.assertRaises(AppError) as caught:
                    action(project_id, slot)
                self.assertEqual((caught.exception.code, caught.exception.slots), ("CONTENT_INVALID", {"항목": "프로젝트 번호"}))
        self.assertEqual(marker.read_text(encoding="utf-8"), "표식", "폴더 밖의 파일은 읽히지도 지워지지도 바뀌지도 않았다")
        self.assertEqual(sorted(path.relative_to(self.tmp).as_posix() for path in self.tmp.rglob("*") if path.is_file()), before, "새 파일도 생기지 않았다")

    def test_when_the_journal_file_cannot_be_deleted_the_result_says_so_and_the_save_still_counts(self):
        """재작업 1 시험 렌즈 Q 권고 R2 — 저장이 끝난 뒤 저널 파일을 못 지우면(읽기 전용 흉내) 알림 글이 결과에 실린다: 파일 이름·경로·오류 글 없이 예외 종류만. 글은 저장된 채이고 저널은 남는다
        (다음에 눌러도 이미 저장된 글이라 새로 보내지 않는다). 파일이 원래 없었으면 알릴 것이 없다."""
        real = Path.unlink

        def refuse(path, *args, **kwargs):
            if path.name.endswith("-blogger_en.json"):
                raise PermissionError(13, "CANARY_읽기_전용")
            return real(path, *args, **kwargs)

        with mock.patch.object(Path, "unlink", refuse):
            result = self.save(self.pid)
        text = " ".join(result.notes)
        self.assertIn("발행 기록 파일을 지우지 못했", text)
        self.assertIn("PermissionError", text)
        for hidden in ("CANARY_", self.pid, "-blogger_en.json", str(self.tmp)):
            self.assertNotIn(hidden, text)
        self.assertEqual((self.variant(self.pid).status, self.journals()), ("DRAFT_SAVED", [f"{self.pid}-blogger_en.json"]))
        journal = flow.BloggerJournal(self.journal_dir())
        with mock.patch.object(Path, "unlink", refuse):
            self.assertIn("PermissionError", journal.remove(self.pid, "blogger_en"))
        self.assertEqual((journal.remove(self.pid, "blogger_en"), self.journals()), (str(), []), "이제 지워진다")
        self.assertEqual(journal.remove(self.pid, "blogger_en"), str(), "없는 파일은 알릴 것이 없다")

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
