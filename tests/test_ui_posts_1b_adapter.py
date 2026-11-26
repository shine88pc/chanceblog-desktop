"""글 검토 화면의 실제 공급자(`ui/posts_adapter.py`)가 글 흐름 1b 에서 더한 길의 시험 — **진짜 서비스**를 임시 데이터 폴더에서 돌린다(네트워크·git·실제 키 없음, PySide6 없이 돈다).

지키는 것:
  1) 복사 준비됨·복사함인 네이버 블로그는 저장된 패키지가 **그 블로그의 것만** 글 모습에 실려 오고(A 와 B 가 섞이지 않는다), 읽는 것만으로는 아무것도 바뀌지 않으며(검토 중인 글을 읽어도 승인되지 않는다) 키·토큰 모양이 든 부분은 `blocked` 로 표시된다.
  2) `복사했어요`·`복사 표시 취소` 는 한 칸만 옮기고(검토 중에서 이 길로 승인되지 않는다), 발행 주소는 **복사함에서만** 기록하며 주소 모양·비밀 모양이 틀리면 아무것도 바뀌지 않고 입력한 주소를 되풀이하지 않는 고정 문장으로 알린다.
  3) 서비스의 `similarity_approved` 는 센 확인창을 거친 요청에서만 참이고 일반 승인은 늘 거짓이다. Pages 의 한 줄 설명·태그 건강 판정은 승인 직전 재검사에도 걸린다.
  4) 발행 기록·작업 로그·검토할 수 있는 네이버 블로그(블로그 관리 등록분 포함)는 읽기뿐이고 데이터 폴더를 한 바이트도 바꾸지 않는다.
  5) 끝까지 돌려도 소켓·하위 프로세스·git 이 불리지 않고, 위험한 서비스 호출은 정해진 함수 안에서 정해진 모양으로만 있다. 가짜 공급자와 같은 일을 하면 같은 상태 순서를 낸다.
  6) (재작업 1, 독립 검증 S 필수-1) 발행 주소는 어댑터가 서비스를 부르기 **전에** 화면과 같은 규칙으로 다시 거른다 — 화면을 건너뛰는 호출도 포트·경로 없음·500자 초과·엔진 전용 키 모양·주소 인자의 토큰·눈에 안 보이는 글자가 든 주소를
     받지 않고(상태 불변·서비스 호출 0), 가짜 공급자와 같은 실패 종류·같은 상태를 낸다. 서비스 자신의 검사는 이보다 좁다(https·네이버 호스트·계정 정보·저장 검사기 여섯 유형).
가짜 비밀은 조립한 문자열이고 실제 글·블로그 이름은 어디에도 없다.
"""
import ast
import hashlib
import os
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import service_support as ss  # noqa: E402

from chanceblog_desktop.content import model as content_model  # noqa: E402
from chanceblog_desktop.content import status as st  # noqa: E402
from chanceblog_desktop.security.refuse import refuse_secret_shapes  # noqa: E402
from chanceblog_desktop.service import blog_profiles, naver_flow, projects, review  # noqa: E402
from chanceblog_desktop.ui import posts_adapter  # noqa: E402
from chanceblog_desktop.ui.core import post_fake, post_rules as rules, posts, text  # noqa: E402

T = text.T
SAFE = lambda *a: None  # noqa: E731
NEVER = lambda: False  # noqa: E731
KEY = ss.KEY
A, B, PAGES = posts.NAVER_A, posts.NAVER_B, posts.PAGES
GOOD_URL = "https://blog.naver.com/exampleaaa/223000000001"
STOP_SENTENCE = "이 영양제를 먹으면 통증이 완전히 사라집니다."
NL = chr(10)
VALUES = posts.PagesValues("경제·일", "ko", "https://images.example.invalid/a.jpg", ("에너지", "생활"), "")
PREFIX = "https://blog.naver.com/x/"                                                    # 글 주소의 정상 앞부분(경로가 있다 — 길이 25)


def engine_keys():
    """가리기 엔진만 아는 키 모양 넷(저장 검사기의 여섯 유형 밖) — 실행 때 조각을 이어 만든다(소스에 키 글자를 두지 않는다 — `tests/scan_samples.py` 방식)."""
    return {"groq": "gs" + "k_" + "I" * 44, "openai-project": "sk-" + "proj-" + "F" * 30, "slack": "xo" + "xb-" + "1234567890-" + "E" * 20, "stripe": "sk" + "_live_" + "K" * 28}


def bad_addresses():
    """화면 규칙(`rules.naver_url_problem`)은 거절하는데 서비스의 두 검사(`refuse_secret_shapes`·`_published_url`)는 받아 버리던 주소들 → (이름, 주소, 기대하는 실패 종류).
    독립 검증 S 의 탐침(`probe_service.py url`)이 찾은 입력이다: 포트·경로 없음·500자 초과·엔진 전용 키 모양·주소 인자의 토큰, 그리고 눈에 안 보이는 글자(참고-1).
    실패 종류는 서비스가 같은 주소에 내던 것과 같다 — 저장 검사기가 아는 여섯 유형(`KEY` 는 그 하나)이 든 주소는 `secret`, 그 밖의 거절(엔진만 아는 키 모양·주소 속 계정 정보 포함)은 `address`."""
    cases = [("port 443", "https://blog.naver.com:443/exampleaaa/1", "address"), ("empty port", "https://blog.naver.com:/exampleaaa/1", "address"), ("no path", "https://blog.naver.com", "address"),
             ("slash only", "https://blog.naver.com/", "address"), ("double slash", "https://blog.naver.com//x", "address"), ("question mark only", "https://blog.naver.com?x=1", "address"),
             ("501 chars", PREFIX + "1" * (501 - len(PREFIX)), "address"), ("5000 chars", PREFIX + "1" * 5000, "address"), ("token argument", PREFIX + "1?tok" + "en=abcdefghijklmnop1234", "address"),
             ("http scheme", "http://blog.naver.com/x/1", "address"), ("other host", "https://example.invalid/x/1", "address"), ("account info", "https://user:pw@blog.naver.com/x/1", "address"), ("empty", "", "address"),
             ("scanner key in the path", PREFIX + KEY, "secret")]
    cases += [(f"{name} key in the path", PREFIX + key, "address") for name, key in engine_keys().items()]
    hidden = {"NUL": chr(0), "DEL": chr(0x7F), "RLO": chr(0x202E), "BOM": chr(0xFEFF), "ZWSP": chr(0x200B), "soft hyphen": chr(0xAD), "tag letter": chr(0xE0041)}
    for name, char in hidden.items():
        cases += [(f"{name} inside", "https://blog.naver.com/x" + char + "/1", "address"), (f"{name} at the end", GOOD_URL + char, "address"), (f"{name} at the start", char + GOOD_URL, "address")]
    return cases


def hashes(root):
    root = Path(root)
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(root.rglob("*")) if path.is_file()}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ctx = ss.make_ctx(self.tmp.name, repo="")
        ss.naver_profiles(self.ctx)
        self.provider = posts_adapter.ServicePostsProvider(context_factory=lambda data_dir=None: self.ctx)
        self.root = Path(self.tmp.name)

    def new_post(self, title="에너지 절약 습관", body=None):
        return self.provider.import_post(posts.ImportRequest("markdown", title, body if body is not None else ss.ko_text()), SAFE, NEVER).detail

    def review(self, project_id, platform=A, values=None):
        return self.provider.review_post(posts.ReviewRequest(project_id, platform, values if platform == PAGES else None), SAFE, NEVER)

    def approve(self, project_id, platform=A, revision=1, ack=False, pages=None):
        return self.provider.approve_post(posts.ApproveRequest(project_id, platform, revision, ack, pages), SAFE, NEVER)

    def ready(self, project_id, platform=A, ack=False):
        self.review(project_id, platform)
        return self.approve(project_id, platform, ack=ack)

    def copied(self, project_id, platform=A, flag=True):
        return self.provider.mark_copied(posts.CopiedRequest(project_id, platform, flag), SAFE, NEVER)

    def record(self, project_id, url, platform=A):
        return self.provider.record_published(posts.RecordRequest(project_id, platform, url), SAFE, NEVER)

    def failure_of(self, call, *args, **kwargs):
        with self.assertRaises(posts.PostFailure) as raised:
            call(*args, **kwargs)
        return raised.exception

    def status(self, project_id, platform=A):
        return ss.status_of(self.ctx, project_id, platform)

    def variant(self, project_id, platform=A):
        return projects.show_project(self.ctx, project_id).variant(platform)


class PostsAdapterPackageTest(Base):
    def test_a_ready_post_comes_back_with_the_stored_package_of_that_blog_only(self):
        project_id = self.new_post().project_id
        outcome = self.ready(project_id, A)
        self.assertEqual((outcome.kind, outcome.detail.platform(A).status), ("approved", st.READY_TO_COPY))
        package = outcome.detail.package(A)
        self.assertIsNone(outcome.detail.package(B))
        self.assertIsNone(outcome.detail.package(PAGES))
        stored = review.read_naver_package(self.ctx.reading_only(), project_id, "naver_a")
        self.assertEqual((package.platform, package.title, package.body, package.tags, package.copy_text), ("naver_a", "에너지 절약 습관", stored.package.body_text, "#생활", stored.copy_text))
        self.assertEqual((package.chars, package.paragraphs, package.images, package.blocked, package.sample), (stored.package.chars, stored.package.paragraphs, 0, (), False))
        self.assertIn("[제목]", package.copy_text)
        self.assertTrue(package.checklist and all(isinstance(item, str) for item in package.checklist))

    def test_loading_a_ready_post_gives_the_same_package_and_changes_no_byte(self):
        project_id = self.new_post().project_id
        wanted = self.ready(project_id, A).detail.package(A)
        before = hashes(self.ctx.workspace.root)
        loaded = self.provider.load_post(project_id, SAFE, NEVER)
        self.assertEqual(loaded.package(A), wanted)
        self.assertEqual(hashes(self.ctx.workspace.root), before)

    def test_a_post_that_is_still_in_review_has_no_package_and_loading_it_never_approves_it(self):
        project_id = self.new_post().project_id
        self.review(project_id, A)
        loaded = self.provider.load_post(project_id, SAFE, NEVER)
        self.assertEqual((loaded.packages, loaded.platform(A).status), ((), st.REVIEW_REQUIRED))
        self.assertEqual(self.status(project_id), st.REVIEW_REQUIRED)

    def test_blog_a_and_blog_b_are_independent_packages_with_their_own_tags(self):
        project_id = self.new_post().project_id
        self.ready(project_id, A)
        self.review(project_id, B)
        outcome = self.approve(project_id, B, ack=True)                         # 같은 글이라 많이 비슷하다 — 알고도 승인(센 확인창을 거친 요청)
        first, second = outcome.detail.package(A), outcome.detail.package(B)
        self.assertEqual((first.platform, first.tags, second.platform, second.tags), ("naver_a", "#생활", "naver_b", "#정보"))
        self.assertEqual({item.platform for item in outcome.detail.packages}, {"naver_a", "naver_b"})

    def test_a_stored_package_with_a_key_shaped_text_marks_those_copies_blocked_and_leaks_nothing(self):
        project_id = self.new_post().project_id
        ss.inject_text(self.ctx, project_id, text=ss.ko_text() + NL + NL + "본문 줄 " + KEY + " 이어지는 글입니다.")
        self.review(project_id, A)
        review.grant_approval(self.ctx, project_id, "naver_a")                      # 서비스는 네이버 승인에서 본문의 키 모양을 보지 않는다 — 이미 밖에서 승인된 글을 흉내 낸다(어댑터의 승인은 막는다)
        loaded = self.provider.load_post(project_id, SAFE, NEVER)
        package = loaded.package(A)
        self.assertEqual(sorted(package.blocked), ["all", "body"])
        self.assertNotIn(KEY[:10], repr(loaded) + repr(package))
        self.assertEqual(self.failure_of(self.approve, project_id, B, 2).kind, "state", "검토하지 않은 블로그는 승인하지 않는다")

    def test_a_stored_package_with_an_engine_only_key_hidden_behind_a_word_and_an_invisible_character_marks_those_copies_blocked(self):
        """재작업 1(독립 검증 S 권고-2): 저장 검사기 여섯 유형 밖의 키 모양(엔진만 안다)이 낱말 + 숨은 글자 뒤에 붙어 승인까지 지난 글도 복사 가드가 막는다 — 엔진은 그 모양을 그대로는 가리지 못한다(임시 방어)."""
        key = engine_keys()["groq"]
        project_id = self.new_post().project_id
        ss.inject_text(self.ctx, project_id, text=ss.ko_text() + NL + NL + "본문 줄 word" + chr(0x200B) + key + " 이어지는 글입니다.")
        self.review(project_id, A)
        review.grant_approval(self.ctx, project_id, "naver_a")
        loaded = self.provider.load_post(project_id, SAFE, NEVER)
        package = loaded.package(A)
        self.assertIn(chr(0x200B) + key[:6], package.body, "숨은 글자가 렌더링을 지나서도 남아 있어야 이 시험이 뜻을 가진다")
        self.assertEqual(sorted(package.blocked), ["all", "body"])
        self.assertNotIn(key[:10], repr(loaded) + repr(package))

    def test_a_damaged_stored_package_is_left_out_and_the_rest_still_loads(self):
        project_id = self.new_post().project_id
        self.ready(project_id, A)
        with self.ctx.store() as store:
            project = store.load(project_id)
            project.variant("naver_a").rendered = "{"
            store.save(project)
        loaded = self.provider.load_post(project_id, SAFE, NEVER)
        self.assertEqual((loaded.packages, loaded.platform(A).status), ((), st.READY_TO_COPY))

    def test_every_write_outcome_that_shows_a_ready_post_carries_the_package(self):
        project_id = self.new_post().project_id
        self.ready(project_id, A)
        self.assertEqual(self.copied(project_id).detail.package(A).platform, "naver_a")
        self.assertEqual(self.copied(project_id, A, False).detail.package(A).platform, "naver_a")
        self.assertEqual(self.provider.revoke_post(posts.RevokeRequest(project_id, A), SAFE, NEVER).detail.packages, (), "승인을 취소하면 패키지 카드가 사라진다")


class PostsAdapterCopiedAndRecordTest(Base):
    def test_the_copy_mark_and_the_address_follow_the_services_steps(self):
        project_id = self.new_post().project_id
        self.ready(project_id, A)
        outcome = self.copied(project_id)
        self.assertEqual((outcome.kind, outcome.detail.platform(A).status), ("copied", st.COPY_COMPLETED))
        back = self.copied(project_id, A, False)
        self.assertEqual((back.kind, back.detail.platform(A).status), ("uncopied", st.READY_TO_COPY))
        self.copied(project_id)
        done = self.record(project_id, GOOD_URL)
        self.assertEqual((done.kind, done.detail.platform(A).status, done.detail.platform(A).published_url), ("recorded", st.PUBLISHED_MANUAL, GOOD_URL))
        self.assertRegex(done.detail.platform(A).published_at, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
        self.assertEqual(done.detail.packages, (), "직접 발행함에는 복사용 패키지가 없다")
        self.assertEqual(self.variant(project_id).published_url, GOOD_URL)

    def test_the_address_is_recorded_only_after_the_copy_mark(self):
        project_id = self.new_post().project_id
        self.ready(project_id, A)
        failure = self.failure_of(self.record, project_id, GOOD_URL)
        self.assertEqual((failure.kind, failure.user_message), ("state", T["post_fail_state"]))
        self.assertEqual((self.status(project_id), self.variant(project_id).published_url), (st.READY_TO_COPY, None), "복사 표시 없이는 아무것도 바뀌지 않는다")
        for bad in (PAGES, "github_pages", "naver_c"):
            self.assertEqual(self.failure_of(self.record, project_id, GOOD_URL, bad).kind, "state")

    def test_a_bad_address_changes_nothing_and_the_sentence_never_repeats_it(self):
        project_id = self.new_post().project_id
        self.ready(project_id, A)
        self.copied(project_id)
        for bad, kind in (("http://blog.naver.com/x/1", "address"), ("https://example.invalid/x/1", "address"), ("https://user:pw@blog.naver.com/x/1", "address"), ("blog.naver.com/x/1", "address"), ("", "address"),
                          (f"https://blog.naver.com/x/{KEY}", "secret")):
            with self.subTest(url=bad[:30]):
                failure = self.failure_of(self.record, project_id, bad)
                self.assertEqual(failure.kind, kind)
                self.assertNotIn(KEY[:10], failure.user_message + repr(failure.__dict__))
                self.assertNotIn("pw", failure.user_message)
                self.assertEqual((self.status(project_id), self.variant(project_id).published_url), (st.COPY_COMPLETED, None))
        self.assertEqual(self.failure_of(self.record, project_id, "http://blog.naver.com/x/1").user_message, T["post_fail_address"])

    def test_the_copy_mark_never_approves_a_post_that_is_in_review_or_not_started(self):
        project_id = self.new_post().project_id
        for flag in (True, False):
            self.assertEqual(self.failure_of(self.copied, project_id, A, flag).kind, "state", "시작 전")
        self.review(project_id, A)
        for flag in (True, False):
            self.assertEqual(self.failure_of(self.copied, project_id, A, flag).kind, "state", "검토 중")
        self.assertEqual(self.status(project_id), st.REVIEW_REQUIRED, "복사 표시 취소가 검토 중인 글을 승인해 버리지 않았다")
        self.assertEqual(self.failure_of(self.copied, project_id, PAGES).kind, "state")

    def test_the_other_blog_is_not_touched(self):
        project_id = self.new_post().project_id
        self.ready(project_id, A)
        self.review(project_id, B)
        self.approve(project_id, B, ack=True)
        self.copied(project_id, A)
        self.assertEqual((self.status(project_id, A), self.status(project_id, B)), (st.COPY_COMPLETED, st.READY_TO_COPY))

    def test_a_missing_post_is_a_not_found_sentence(self):
        for call in (self.copied, lambda project_id: self.record(project_id, GOOD_URL)):
            failure = self.failure_of(call, "zzzzzzzzzzzz")
            self.assertEqual((failure.kind, failure.code), ("notfound", "CONTENT_NOT_FOUND"))


class PostsAdapterAddressRecheckTest(Base):
    """재작업 1(독립 검증 S 필수-1): 어댑터가 서비스를 부르기 **전에** 화면과 같은 규칙(`rules.naver_url_problem`)으로 발행 주소를 다시 건다. 이전에는 화면을 건너뛰는 호출이 포트(:443)·경로 없음·501자·5000자·
    엔진 전용 키 모양·주소 인자의 토큰이 든 주소를 서비스에 그대로 넘겨 직접 발행함으로 저장됐다(서비스의 두 검사는 https·네이버 호스트·계정 정보·저장 검사기 여섯 유형뿐이다)."""

    def at_copied(self):
        project_id = self.new_post().project_id
        self.ready(project_id, A)
        self.copied(project_id)
        return project_id

    def test_every_address_the_screen_refuses_is_refused_by_the_adapter_and_changes_nothing(self):
        project_id = self.at_copied()
        for name, url, kind in bad_addresses():
            with self.subTest(case=name):
                self.assertNotEqual(rules.naver_url_problem(url), "", "시험 값이 정말 화면이 거절하는 모양이다")
                failure = self.failure_of(self.record, project_id, url)
                self.assertEqual((failure.kind, failure.code), (kind, "NAVER_PUBLISH_URL_INVALID" if kind == "address" else "SECRET_SHAPE_FOUND"))
                self.assertEqual(failure.user_message, T["post_fail_address"] if kind == "address" else T["post_fail_secret_plain"], "고정 문장 — 입력한 주소가 문장에 없다")
                self.assertEqual((self.status(project_id), self.variant(project_id).published_url, self.variant(project_id).published_at), (st.COPY_COMPLETED, None, None), "거절하면 상태는 그대로이고 기록은 0")

    def test_a_refusal_leaves_the_data_folder_byte_for_byte_as_it_was(self):
        project_id = self.at_copied()
        before = hashes(self.ctx.workspace.root)
        for name, url, _kind in bad_addresses():
            with self.subTest(case=name):
                self.failure_of(self.record, project_id, url)
        self.assertEqual(hashes(self.ctx.workspace.root), before)

    def test_the_service_is_not_even_called_for_them(self):
        project_id = self.at_copied()
        with mock.patch.object(review, "record_naver_published", side_effect=AssertionError("서비스를 불러서는 안 된다")) as service:
            for name, url, kind in bad_addresses():
                with self.subTest(case=name):
                    self.assertEqual(self.failure_of(self.record, project_id, url).kind, kind)
        service.assert_not_called()

    def test_what_the_screen_accepts_reaches_the_service_trimmed_the_way_the_screen_sends_it(self):
        project_id = self.at_copied()
        accepted = [GOOD_URL, "https://m.blog.naver.com/exampleaaa/223000000001", "HTTPS://BLOG.NAVER.COM/x/1", "https://blog.naver.com/PostView.naver?blogId=exampleaaa&logNo=223", "  " + GOOD_URL + "  ", GOOD_URL + NL]
        with mock.patch.object(review, "record_naver_published", return_value=None) as service:
            for url in accepted:
                with self.subTest(url=url.strip()[:40]):
                    self.assertEqual(rules.naver_url_problem(url), "")
                    self.assertEqual(self.record(project_id, url).kind, "recorded")
                    self.assertEqual(service.call_args.args[1:], (project_id, "naver_a", url.strip()), "화면처럼 앞뒤 공백을 떼어 서비스에 넘긴다")
            self.assertEqual(service.call_count, len(accepted))

    def test_the_adapter_decides_exactly_like_the_screen_for_a_wide_set_of_inputs(self):
        project_id = self.at_copied()
        more = ["", "   ", "blog.naver.com/x/1", "https://blog.naver.com.evil.example/x/1", "https://evil.example/blog.naver.com/x/1", "https://naver.com/x/1", "ftp://blog.naver.com/x/1", "javascript:alert(1)",
                "https://blog.naver.com/x /1", "https://blog.naver.com/x/1#comment", "https://blog.naver.com/x/1?v=1", "https://blog.naver.com/exampleaaa", "https://BLOG.Naver.COM/x/1"]
        inputs = [url for _name, url, _kind in bad_addresses()] + more + [GOOD_URL]
        with mock.patch.object(review, "record_naver_published", return_value=None) as service:
            for url in inputs:
                with self.subTest(url=url[:40]):
                    before = service.call_count
                    if rules.naver_url_problem(url):
                        self.failure_of(self.record, project_id, url)
                        self.assertEqual(service.call_count, before, "화면이 거절하는 주소는 서비스까지 가지 않는다")
                    else:
                        self.record(project_id, url)
                        self.assertEqual(service.call_count, before + 1, "화면이 받는 주소는 서비스가 판단한다")

    def test_what_the_adapter_lets_through_the_services_narrower_checks_accept_too(self):
        """어댑터(= 화면 규칙)를 지난 주소는 서비스의 더 좁은 두 검사(`refuse_secret_shapes`·`_published_url`)도 지난다 — 어댑터 다시 걸기가 서비스를 건너뛰는 것이 아니라 서비스 앞에 더하는 것임을 견준다(문서 8-3)."""
        accepted = [GOOD_URL, "https://m.blog.naver.com/exampleaaa/223000000001", "HTTPS://BLOG.NAVER.COM/x/1", "https://blog.naver.com/PostView.naver?blogId=exampleaaa&logNo=223", "https://blog.naver.com/x/1#comment",
                    "https://blog.naver.com/x/1?v=1", "https://BLOG.Naver.COM/exampleaaa/1", "  " + GOOD_URL + "  ", GOOD_URL + NL]
        inputs = accepted + [url for _name, url, _kind in bad_addresses()] + ["blog.naver.com/x/1", "https://blog.naver.com.evil.example/x/1", "https://naver.com/x/1", "ftp://blog.naver.com/x/1", "https://blog.naver.com/x /1"]
        passed = [url for url in inputs if rules.naver_url_problem(url) == ""]
        self.assertGreaterEqual(len(passed), len(accepted), "화면이 받는 주소를 실제로 모았다")
        for url in passed:
            with self.subTest(url=url.strip()[:40]):
                refuse_secret_shapes({"발행 주소": url.strip()}, "저장")
                content_model._published_url("naver_a", url.strip())

    def test_a_wrong_state_is_still_a_state_failure_whatever_the_address_is(self):
        project_id = self.new_post().project_id
        self.ready(project_id, A)
        for url in (GOOD_URL, "https://blog.naver.com", PREFIX + engine_keys()["groq"]):
            with self.subTest(url=url[:40]):
                self.assertEqual(self.failure_of(self.record, project_id, url).kind, "state", "복사 표시 전에는 주소 검사보다 상태가 먼저다 — 가짜 공급자와 같다")
        self.assertEqual((self.status(project_id), self.variant(project_id).published_url), (st.READY_TO_COPY, None))

    def test_a_good_address_is_still_recorded_through_the_real_service_after_the_refusals(self):
        project_id = self.at_copied()
        for name, url, _kind in bad_addresses()[:6]:
            self.failure_of(self.record, project_id, url)
        done = self.record(project_id, "  " + GOOD_URL + "  ")
        self.assertEqual((done.kind, done.detail.platform(A).status, done.detail.platform(A).published_url), ("recorded", st.PUBLISHED_MANUAL, GOOD_URL))


class PostsAdapterSimilarityTest(Base):
    def test_two_nearly_identical_blogs_are_refused_without_the_acknowledgement_and_pass_with_it(self):
        project_id = self.new_post().project_id
        self.ready(project_id, A)
        self.review(project_id, B)
        failure = self.failure_of(self.approve, project_id, B)
        self.assertEqual((failure.kind, failure.code, failure.user_message), ("similarity", "NAVER_SIMILARITY_HIGH", T["post_fail_similarity"]))
        self.assertEqual(self.status(project_id, B), st.REVIEW_REQUIRED, "거절되면 아무것도 바뀌지 않는다")
        outcome = self.approve(project_id, B, ack=True)
        self.assertEqual(outcome.detail.platform(B).status, st.READY_TO_COPY)

    def test_only_a_real_true_counts_as_the_acknowledgement(self):
        project_id = self.new_post().project_id
        self.ready(project_id, A)
        self.review(project_id, B)
        for fake_true in (1, "yes", "True", [1], 1.0):
            with self.subTest(value=fake_true):
                self.assertEqual(self.failure_of(self.approve, project_id, B, 1, fake_true).kind, "similarity")
        self.assertEqual(self.status(project_id, B), st.REVIEW_REQUIRED)

    def test_the_acknowledgement_does_not_skip_the_other_checks(self):
        project_id = self.new_post(body=ss.ko_text() + NL + NL + STOP_SENTENCE).project_id
        self.review(project_id, A)
        failure = self.failure_of(self.approve, project_id, A, 1, True)
        self.assertEqual((failure.kind, failure.user_message), ("gate", T["post_fail_blocked"]), "건강 효과 단정은 알고도 승인으로 넘을 수 없다")
        self.assertEqual(self.status(project_id), st.REVIEW_REQUIRED)

    def test_the_acknowledgement_means_nothing_for_pages(self):
        project_id = self.new_post().project_id
        self.review(project_id, PAGES, VALUES)
        outcome = self.approve(project_id, PAGES, 1, True)
        self.assertEqual(outcome.detail.platform(PAGES).status, st.APPROVED)


class PostsAdapterHealthExtraTest(Base):
    def test_a_stop_sentence_in_the_description_stops_the_report_and_the_approval_re_check(self):
        project_id = self.new_post().project_id
        values = posts.PagesValues("경제·일", "ko", "https://images.example.invalid/a.jpg", ("에너지",), STOP_SENTENCE)
        outcome = self.review(project_id, PAGES, values)
        self.assertEqual((outcome.review.health.stage, outcome.review.pages), ("stop", values))
        self.assertTrue(any(T["post_where_description"] in place for place in outcome.review.health.places))
        failure = self.failure_of(self.approve, project_id, PAGES, 1, False, outcome.review.pages)
        self.assertEqual((failure.kind, failure.user_message), ("gate", T["post_fail_blocked"]))
        self.assertEqual(self.status(project_id, PAGES), st.REVIEW_REQUIRED)

    def test_a_stop_sentence_in_a_tag_does_the_same_and_a_calm_value_passes(self):
        project_id = self.new_post().project_id
        values = posts.PagesValues("경제·일", "ko", "https://images.example.invalid/a.jpg", (STOP_SENTENCE,), "")
        outcome = self.review(project_id, PAGES, values)
        self.assertEqual(outcome.review.health.stage, "stop")
        self.assertEqual(self.failure_of(self.approve, project_id, PAGES, 1, False, outcome.review.pages).kind, "gate")
        calm = self.new_post(title="조용한 글").project_id
        quiet = self.review(calm, PAGES, posts.PagesValues("경제·일", "ko", "https://images.example.invalid/a.jpg", ("에너지",), "오늘의 산책을 기록했어요."))
        self.assertEqual(quiet.review.health.stage, "general")
        self.assertEqual(self.approve(calm, PAGES, 1, False, quiet.review.pages).detail.platform(PAGES).status, st.APPROVED)

    def test_naver_reports_carry_no_pages_values(self):
        project_id = self.new_post().project_id
        self.assertIsNone(self.review(project_id, A).review.pages)


class PostsAdapterReadsTest(Base):
    def test_the_history_lists_posts_after_the_approval_with_status_and_address_and_changes_no_byte(self):
        first = self.new_post().project_id
        self.ready(first, A)
        self.copied(first)
        self.record(first, GOOD_URL)
        second = self.new_post(title="두 번째 글").project_id
        self.review(second, PAGES, VALUES)
        self.approve(second, PAGES)
        third = self.new_post(title="검토만 한 글").project_id
        self.review(third, A)
        before = hashes(self.ctx.workspace.root)
        data = self.provider.load_history(SAFE, NEVER)
        self.assertEqual(hashes(self.ctx.workspace.root), before)
        by = {(row.project_id, row.platform): row for row in data.rows}
        self.assertEqual(set(by), {(first, "naver_a"), (second, "github_pages")}, "검토 중인 글은 없다")
        self.assertEqual((by[(first, "naver_a")].status, by[(first, "naver_a")].published_url, by[(second, "github_pages")].status), (st.PUBLISHED_MANUAL, GOOD_URL, st.APPROVED))
        self.assertEqual((data.unreadable, data.state, data.sample, data.offline), (0, "ok", False, False))
        self.assertEqual(by[(first, "naver_a")].title, "에너지 절약 습관")

    def test_a_missing_store_is_an_empty_missing_history_and_nothing_is_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = ss.make_ctx(tmp, repo="")
            provider = posts_adapter.ServicePostsProvider(context_factory=lambda data_dir=None: ctx)
            data = provider.load_history(SAFE, NEVER)
            self.assertEqual((data.rows, data.state, data.unreadable), ((), "missing", 0))
            self.assertFalse(ctx.workspace.root.exists())

    def test_a_broken_store_is_a_sentence_and_the_file_is_not_touched(self):
        self.new_post()
        self.ctx.workspace.store_path.write_bytes(b"not a database at all" * 100)
        before = hashes(self.ctx.workspace.root)
        failure = self.failure_of(self.provider.load_history, SAFE, NEVER)
        self.assertEqual(failure.kind, "corrupt")
        self.assertEqual(hashes(self.ctx.workspace.root), before)

    def test_the_work_log_is_read_split_into_fields_and_nothing_is_written(self):
        folder = self.ctx.workspace.root / "logs"
        folder.mkdir(parents=True)
        (folder / "errors.log").write_text("2026-11-24T05:30:12Z slot KeyError post_view.py:123 < shell.py:45\n손으로 쓴 줄\n2026-11-24T05:31:00Z thread ValueError -\n", encoding="utf-8")
        before = hashes(self.ctx.workspace.root)
        data = self.provider.load_work_log(SAFE, NEVER)
        self.assertEqual(hashes(self.ctx.workspace.root), before)
        self.assertEqual([(line.at, line.source, line.name, line.places) for line in data.lines], [("2026-11-24T05:31:00Z", "thread", "ValueError", ()), ("2026-11-24T05:30:12Z", "slot", "KeyError", ("post_view.py:123", "shell.py:45"))])
        self.assertEqual((data.files, data.skipped, data.older, data.sample), (1, 1, 0, False))

    def test_a_missing_work_log_is_empty_and_nothing_is_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = ss.make_ctx(tmp, repo="")
            provider = posts_adapter.ServicePostsProvider(context_factory=lambda data_dir=None: ctx)
            data = provider.load_work_log(SAFE, NEVER)
            self.assertEqual((data.lines, data.files, data.skipped), ((), 0, 0))
            self.assertFalse(ctx.workspace.root.exists())

    def test_the_work_log_never_hands_out_a_key_shaped_line(self):
        folder = self.ctx.workspace.root / "logs"
        folder.mkdir(parents=True)
        (folder / "errors.log").write_text(f"2026-11-24T05:30:12Z slot {KEY} a.py:1" + NL + "2026-11-24T05:31:00Z main ValueError a.py:2" + NL, encoding="utf-8")
        data = self.provider.load_work_log(SAFE, NEVER)
        self.assertEqual(([line.name for line in data.lines], data.skipped), (["ValueError"], 1))
        self.assertNotIn(KEY[:10], repr(data) + repr([vars(line) for line in data.lines]))

    def test_the_posts_screen_can_review_a_blog_that_is_only_registered_in_the_blog_screen(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        ctx = ss.make_ctx(tmp.name, repo="")
        provider = posts_adapter.ServicePostsProvider(context_factory=lambda data_dir=None: ctx)
        self.assertEqual(provider.load_posts(SAFE, NEVER).profiles, ())
        blog_profiles.save_slot(ctx, "naver_a", {"display_name": "에이 블로그", "blog_ref": "exampleid", "main_topics": ["생활"]}, expected_version=blog_profiles.read_snapshot(ctx).version)
        self.assertEqual(provider.load_posts(SAFE, NEVER).profiles, ("naver_a",))
        project_id = provider.import_post(posts.ImportRequest("markdown", "에너지 절약 습관", ss.ko_text()), SAFE, NEVER).detail.project_id
        outcome = provider.review_post(posts.ReviewRequest(project_id, A, None), SAFE, NEVER)
        self.assertEqual(outcome.detail.platform(A).status, st.REVIEW_REQUIRED)
        self.assertFalse(ctx.workspace.settings_path.exists(), "화면이 설정 파일을 만들지 않았다")
        self.assertEqual(provider.approve_post(posts.ApproveRequest(project_id, A, 1), SAFE, NEVER).detail.package(A).tags, "#생활")

    def test_a_blog_without_any_tag_gets_a_package_sentence_that_names_the_missing_item(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        ctx = ss.make_ctx(tmp.name, repo="")
        provider = posts_adapter.ServicePostsProvider(context_factory=lambda data_dir=None: ctx)
        blog_profiles.save_slot(ctx, "naver_a", {"display_name": "에이 블로그", "blog_ref": "exampleid"}, expected_version=blog_profiles.read_snapshot(ctx).version)
        project_id = provider.import_post(posts.ImportRequest("markdown", "에너지 절약 습관", ss.ko_text()), SAFE, NEVER).detail.project_id
        failure = self.failure_of(provider.review_post, posts.ReviewRequest(project_id, A, None), SAFE, NEVER)
        self.assertEqual((failure.kind, failure.code, failure.user_message), ("package", "NAVER_PACKAGE_INCOMPLETE", T["post_fail_package"].format(field="태그")))


class PostsAdapterShapeTest(unittest.TestCase):
    """위험한 서비스 호출이 정해진 함수 안에서 정해진 모양으로만 있는지 소스를 읽어 못박는다(시험 코드이지 실행 때의 방어가 아니다 — 문서 8절 D-647)."""
    PATH = ROOT / "src" / "chanceblog_desktop" / "ui" / "posts_adapter.py"

    def setUp(self):
        self.tree = ast.parse(self.PATH.read_text(encoding="utf-8"))
        self.parents = {child: parent for parent in ast.walk(self.tree) for child in ast.iter_child_nodes(parent)}

    def calls(self, owner, name):
        return [node for node in ast.walk(self.tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == name and isinstance(node.func.value, ast.Name) and node.func.value.id == owner]

    def function_of(self, node):
        while node is not None and not isinstance(node, ast.FunctionDef):
            node = self.parents.get(node)
        return node.name if node is not None else ""

    def test_the_write_calls_of_1b_each_live_in_exactly_one_method(self):
        for owner, name, method in (("review_service", "record_naver_published", "record_published"), ("review_service", "mark_naver_copied", "mark_copied"), ("review_service", "grant_approval", "approve_post"),
                                    ("review_service", "revoke_approval", "revoke_post"), ("review_service", "request_review", "review_post")):
            with self.subTest(call=name):
                found = self.calls(owner, name)
                self.assertEqual([self.function_of(node) for node in found], [method])

    def test_the_similarity_flag_is_only_ever_the_requests_own_acknowledgement_compared_with_true(self):
        (call,) = self.calls("review_service", "grant_approval")
        keywords = {item.arg: ast.unparse(item.value) for item in call.keywords}
        self.assertEqual(keywords, {"similarity_approved": "request.similarity_ack is True"})
        self.assertNotIn("True", [ast.unparse(arg) for arg in call.args])

    def test_the_package_is_only_read_with_the_read_only_context(self):
        (call,) = self.calls("review_service", "read_naver_package")
        self.assertEqual(ast.unparse(call.args[0]), "ctx.reading_only()")
        self.assertEqual(self.function_of(call), "_packages")
        self.assertEqual(self.calls("review_service", "issue_naver_package"), [])

    def test_recording_checks_the_copied_state_first_and_the_copy_mark_passes_the_flag_through_untouched(self):
        method = next(node for node in ast.walk(self.tree) if isinstance(node, ast.FunctionDef) and node.name == "record_published")
        source = ast.unparse(method)
        self.assertLess(source.index("st.COPY_COMPLETED"), source.index("record_naver_published"))
        (call,) = self.calls("review_service", "mark_naver_copied")
        self.assertEqual({item.arg: ast.unparse(item.value) for item in call.keywords}, {"copied": "request.copied"}, "참·거짓이 아닌 값을 참으로 바꾸지 않고 서비스의 엄격한 검사에 맡긴다")

    def test_the_read_functions_are_called_with_the_context_and_not_with_anything_else(self):
        for owner, name, expected in (("history_service", "list_history", "ctx.reading_only()"), ("worklog_service", "read_work_log", "ctx"), ("profile_service", "profile_keys", "ctx")):
            with self.subTest(call=name):
                (call,) = self.calls(owner, name)
                self.assertEqual([ast.unparse(arg) for arg in call.args], [expected])


class PostsAdapterOutsideZeroTest(Base):
    def test_the_whole_1b_flow_calls_no_socket_no_process_and_no_git_and_writes_only_in_the_data_folder(self):
        git_calls = []
        self.ctx.git = lambda *a, **k: git_calls.append(a)
        outside_before = {path: data for path, data in ss.tree_snapshot(self.root).items() if not path.startswith("data/")}

        def refuse(*args, **kwargs):
            raise AssertionError("바깥과 닿는 호출이 불렸다")

        with mock.patch.object(socket.socket, "connect", refuse), mock.patch.object(subprocess, "Popen", refuse), mock.patch.object(os, "system", refuse):
            project_id = self.new_post().project_id
            self.ready(project_id, A)
            self.review(project_id, B)
            self.approve(project_id, B, ack=True)
            self.provider.load_post(project_id, SAFE, NEVER)
            self.copied(project_id)
            self.copied(project_id, A, False)
            self.copied(project_id)
            self.record(project_id, GOOD_URL)
            self.provider.load_history(SAFE, NEVER)
            self.provider.load_work_log(SAFE, NEVER)
            self.provider.load_posts(SAFE, NEVER)
        self.assertEqual(git_calls, [])
        self.assertEqual([name for name in self.ctx.backend.calls if name[0] not in ("inspect", "expected_url")], [])
        outside_after = {path: data for path, data in ss.tree_snapshot(self.root).items() if not path.startswith("data/")}
        self.assertEqual(outside_after, outside_before)
        inside = sorted(path.relative_to(self.ctx.workspace.root).as_posix() for path in self.ctx.workspace.root.rglob("*") if path.is_file())
        self.assertFalse([path for path in inside if path.startswith(("publish", "backups", "logs"))], inside)


class PostsFakeMatchesRealFor1bTest(Base):
    def run_flow(self, provider, markdown):
        """같은 일을 하고 단계마다의 상태·실패 종류를 모은다 — 가짜와 실제가 같아야 한다."""
        steps = []
        detail = provider.import_post(posts.ImportRequest("markdown", "글", markdown), SAFE, NEVER).detail
        project_id = detail.project_id

        def attempt(label, call):
            try:
                outcome = call()
            except posts.PostFailure as failure:
                steps.append((label, "refused", failure.kind))
                return None
            steps.append((label, outcome.detail.platform(A).status, outcome.detail.package(A) is not None))
            return outcome

        attempt("copy-too-early", lambda: provider.mark_copied(posts.CopiedRequest(project_id, A, True), SAFE, NEVER))
        attempt("uncopy-too-early", lambda: provider.mark_copied(posts.CopiedRequest(project_id, A, False), SAFE, NEVER))
        attempt("record-too-early", lambda: provider.record_published(posts.RecordRequest(project_id, A, GOOD_URL), SAFE, NEVER))
        provider.review_post(posts.ReviewRequest(project_id, A, None), SAFE, NEVER)
        attempt("uncopy-in-review", lambda: provider.mark_copied(posts.CopiedRequest(project_id, A, False), SAFE, NEVER))
        attempt("approve", lambda: provider.approve_post(posts.ApproveRequest(project_id, A, 1), SAFE, NEVER))
        attempt("record-before-copy", lambda: provider.record_published(posts.RecordRequest(project_id, A, GOOD_URL), SAFE, NEVER))
        attempt("copy", lambda: provider.mark_copied(posts.CopiedRequest(project_id, A, True), SAFE, NEVER))
        attempt("copy-twice", lambda: provider.mark_copied(posts.CopiedRequest(project_id, A, True), SAFE, NEVER))
        attempt("record-bad", lambda: provider.record_published(posts.RecordRequest(project_id, A, "http://example.invalid/x"), SAFE, NEVER))
        for name, url, _kind in bad_addresses():                                         # 재작업 1: 서비스가 받아 버리던 주소도 가짜와 실제가 같은 실패 종류로 거절하고 상태는 그대로다(거절 바로 뒤의 상태·주소를 함께 견준다)
            attempt(f"record-bad:{name}", lambda url=url: provider.record_published(posts.RecordRequest(project_id, A, url), SAFE, NEVER))
            peeked = provider.load_post(project_id, SAFE, NEVER).platform(A)
            steps.append((f"after:{name}", peeked.status, peeked.published_url))
        attempt("uncopy", lambda: provider.mark_copied(posts.CopiedRequest(project_id, A, False), SAFE, NEVER))
        attempt("copy-again", lambda: provider.mark_copied(posts.CopiedRequest(project_id, A, True), SAFE, NEVER))
        attempt("record", lambda: provider.record_published(posts.RecordRequest(project_id, A, GOOD_URL), SAFE, NEVER))
        attempt("record-twice", lambda: provider.record_published(posts.RecordRequest(project_id, A, GOOD_URL), SAFE, NEVER))
        return steps

    def test_the_fake_and_the_real_provider_give_the_same_steps_for_the_whole_naver_road(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = ss.make_ctx(tmp, repo="")
            ss.naver_profiles(ctx)
            real = self.run_flow(posts_adapter.ServicePostsProvider(context_factory=lambda data_dir=None: ctx), ss.ko_text())
        fake = self.run_flow(post_fake.FakePostsProvider("empty"), ss.ko_text())
        self.assertEqual(real, fake)
        self.assertEqual([step[0] for step in real][-3:], ["copy-again", "record", "record-twice"])
        self.assertEqual(real[-2][1], st.PUBLISHED_MANUAL)
        wanted = {f"record-bad:{name}": kind for name, _url, kind in bad_addresses()}
        self.assertEqual({step[0]: step[2] for step in real if step[0] in wanted}, wanted, "서비스가 받아 버리던 주소도 둘 다 같은 종류로 거절한다")
        self.assertTrue(all(step[1] == "refused" for step in real if step[0] in wanted))
        after = [step for step in real if step[0].startswith("after:")]
        self.assertEqual(len(after), len(wanted))
        self.assertEqual({step[1:] for step in after}, {(st.COPY_COMPLETED, "")}, "거절한 바로 뒤에도 복사함이고 기록한 주소는 없다")


if __name__ == "__main__":
    unittest.main()
