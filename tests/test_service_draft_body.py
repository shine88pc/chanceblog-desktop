"""명령줄 `draft body` 와 서비스 함수(`service/draft_body.py`) 시험 — 같은 프로세스에서 돌린다(진짜 프로세스 시험은 아래 `ProcessTest` 한 곳).

지키는 것:
  1) **읽기만 한다** — 데이터 폴더의 파일을 만들지도 바꾸지도 않고(바이트 그대로, 보관함·설정·채널 프로필 파일·`.bak`·잠금 파일 포함), 보관함은 읽기 전용으로 열며 옛 구조 파일도 올리지 않는다.
     네트워크·git·배포 확인을 쓰지 않는다. 후보와 그 상태는 그대로다.
  2) 후보 번호는 `candidates` 명령과 같은 규칙. 대상 블로그는 네이버 A·B 만 — 주지 않으면 고른(없으면 추천한) 블로그 가운데 첫 번째 네이버 블로그이고, 네이버가 아닌 블로그는 `DRAFT_OPTION_INVALID`.
  3) 네이버 프로필(설정 파일)과 채널 프로필(주제 엔진 파일)이 없으면 멈추지 않고 기본값으로 만들고, 있으면 그 값이 쓰이며, 깨진 파일은 숨기지 않는다.
  4) 출력은 쉬운 한국어(영문 상태 코드·긴 번호 없음), `--json` 은 `ok/command/data`, 틀린 입력은 종료 코드 1, 사용법 오류는 2, 화면에 나가는 글에서 키 모양은 가려진다. `draft plan` 은 그대로이고 두 명령의 선택 입력 옵션 이름이 같다.
  5) **안전 판정**(독립 검증 H2): 주제 엔진이 자동 초안 중지로 판정하는 후보는 본문을 만들지 않고(입력을 되풀이하지 않는 쉬운 오류), 근거 확인 필요·협찬 낱말·단정 낱말은 확인 권장 맨 위의 경고다. 키 모양 11종은 어느 칸에서도 출력에 나오지 않는다.
"""
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import service_support as ss  # noqa: E402
import store_v1  # noqa: E402

from chanceblog_desktop.check import claims  # noqa: E402
from chanceblog_desktop.content import candidates as cd  # noqa: E402
from chanceblog_desktop.content import draft_body as content_body  # noqa: E402
from chanceblog_desktop.content.draft_options import DraftOptions  # noqa: E402
from chanceblog_desktop.content.profiles import NaverProfile  # noqa: E402
from chanceblog_desktop.content.store import Store  # noqa: E402
from chanceblog_desktop.service import candidates as svc  # noqa: E402
from chanceblog_desktop.service import cli, draft_body  # noqa: E402
from chanceblog_desktop.service import topic_files as tf  # noqa: E402
from chanceblog_desktop.service.context import write_json  # noqa: E402
from chanceblog_desktop.topics import channels, safety  # noqa: E402

ENGLISH = ("usage:", "positional arguments", "options:", "optional arguments", "show this help message and exit")
STATUS_CODES = re.compile(r"\b(?:NEW|REVIEW|SELECTED|HOLD|REJECTED)\b")
LONG_ID = re.compile(r"\b[0-9a-f]{32}\b")
KEY = "AI" + "za" + "A" * 35                                              # 구글 키 모양의 가짜 값(저장소에 키 문자열을 두지 않는다)
INPUT_OPTIONS = {"--message", "--experience", "--opinion", "--must-include", "--exclude", "--audience", "--length", "--title-direction", "--url", "--price-date", "--conclusion"}


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.ctx = ss.make_ctx(self.tmp, repo="")
        self.root = self.ctx.workspace.root

    def run_cli(self, *argv):
        return ss.run_cli(self.ctx, *argv)

    def ok(self, *argv):
        code, out, err = self.run_cli(*argv)
        self.assertEqual((code, err), (0, ""), (argv, out, err))
        return out

    def fails(self, *argv, code=1):
        got, out, err = self.run_cli(*argv)
        self.assertEqual((got, out), (code, ""), (argv, out, err))
        self.assertNotIn("Traceback", err)
        return err

    def data(self, *argv):
        payload = json.loads(self.ok("--json", *argv))
        self.assertTrue(payload["ok"], payload)
        return payload["data"]

    def add(self, topic="무선 청소기 선택 기준", keyword="무선 청소기", blogs=("naver_a",), **fields):
        self.ctx.clock.advance(seconds=1)
        return svc.add_candidate(self.ctx, topic=topic, keyword=keyword, blogs=blogs, **fields).row

    def snapshot(self):
        return ss.tree_snapshot(self.root) if self.root.exists() else None

    def write_channels(self, **changes):
        """채널 프로필 파일을 쓴다 — naver_a 의 칸을 `changes` 로 바꾼 다섯 프로필."""
        import dataclasses
        profiles = [dataclasses.replace(item, **changes) if item.key == "naver_a" else item for item in channels.default_profiles()]
        write_json(tf.topic_paths(self.ctx.workspace).profiles, channels.profiles_to_dict(profiles))


class ReadOnlyTest(Base):
    def test_without_a_store_it_says_the_candidate_is_missing_and_creates_nothing(self):
        err = self.fails("draft", "body", "1")
        self.assertIn("CANDIDATE_NOT_FOUND", err)
        self.assertFalse(self.root.exists())
        code, out, err = self.run_cli("--json", "draft", "body", "1")
        payload = json.loads(out)
        self.assertEqual((code, payload["command"], payload["error"]["code"]), (1, "draft body", "CANDIDATE_NOT_FOUND"))
        self.assertFalse(self.root.exists())

    def test_a_body_changes_no_file_in_the_data_folder_and_creates_no_settings_channel_file_backup_or_lock(self):
        self.add(sub_keywords=("청소기 추천",))
        before = self.snapshot()
        self.assertEqual(set(before), {"chanceblog.db"})
        self.ok("draft", "body", "1", "--blog", "naver_a")
        self.ok("draft", "body", "1", "--blog", "naver_a", "--experience", "지난달부터 써 왔어요.", "--url", "https://example.com/a", "--length", "2500+", "--must-include", "문장 하나예요.")
        self.data("draft", "body", "1")
        self.assertEqual(self.snapshot(), before)

    def test_with_profiles_and_a_channel_file_saved_nothing_is_rewritten(self):
        self.add(blogs=("naver_a", "naver_b"))
        ss.naver_profiles(self.ctx)
        self.write_channels(tone="정중한 말투", categories=("가전 고르기",))
        before = self.snapshot()
        self.assertIn("settings.json", before)
        self.assertIn("topic_engine/channel_profiles.json", before)
        self.ok("draft", "body", "1", "--blog", "naver_a")
        self.ok("draft", "body", "1", "--blog", "naver_b")
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(any(name.endswith((".bak", ".tmp", ".lock")) for name in self.snapshot()))
        self.assertFalse((self.root / "locks").exists())

    def test_the_store_is_opened_read_only_and_never_written(self):
        self.add()
        opened = []
        original = Store.open.__func__

        def spy(cls, path, **kwargs):
            opened.append(kwargs)
            return original(cls, path, **kwargs)

        with mock.patch.object(Store, "open", classmethod(spy)):
            self.ok("draft", "body", "1")
        self.assertTrue(opened)
        self.assertTrue(all(kwargs.get("migrate") is False for kwargs in opened), opened)

    def test_an_old_structure_file_is_not_upgraded_and_has_no_candidates(self):
        self.root.mkdir(parents=True)
        store_v1.make_v1_file(self.ctx.workspace.store_path)
        before = self.snapshot()
        err = self.fails("draft", "body", "1")
        self.assertIn("CANDIDATE_NOT_FOUND", err)
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(list(self.root.glob("*.bak")))

    def test_no_network_git_or_deploy_check_is_used(self):
        self.add(blogs=("naver_a", "naver_b"))
        ss.naver_profiles(self.ctx)
        with mock.patch.object(socket, "socket", side_effect=AssertionError("네트워크")), mock.patch.object(socket, "getaddrinfo", side_effect=AssertionError("이름 찾기")):
            self.ok("draft", "body", "1", "--blog", "naver_a", "--url", "https://example.com/a")
        self.assertEqual(self.ctx.backend.calls, [])

    def test_the_candidate_and_its_status_are_unchanged(self):
        row = self.add()
        svc.select_candidate(self.ctx, "1", "naver_a")
        before = svc.show_candidate(self.ctx, "1").to_dict()
        self.ok("draft", "body", "1", "--blog", "naver_a")
        self.assertEqual(svc.show_candidate(self.ctx, "1").to_dict(), before)
        self.assertEqual(before["candidate"]["status"], cd.SELECTED)
        self.assertEqual(row.candidate.status, cd.NEW)

    def test_the_same_command_twice_prints_the_same_text(self):
        self.add(sub_keywords=("청소기 추천",))
        first = self.ok("draft", "body", "1", "--blog", "naver_a")
        second = self.ok("draft", "body", "1", "--blog", "naver_a")
        self.assertEqual(first, second)
        self.assertEqual(self.data("draft", "body", "1"), self.data("draft", "body", "1"))

    def test_plan_output_does_not_change_when_a_body_was_made_in_between(self):
        self.add(blogs=("naver_a", "naver_b"))
        before = self.ok("draft", "plan", "1", "--blog", "naver_a", "--experience", "지난달부터 써 왔어요.")
        self.ok("draft", "body", "1", "--blog", "naver_a", "--experience", "지난달부터 써 왔어요.")
        self.assertEqual(self.ok("draft", "plan", "1", "--blog", "naver_a", "--experience", "지난달부터 써 왔어요."), before)


class ResolveCandidateTest(Base):
    def test_ordinals_and_id_prefixes_choose_the_candidate(self):
        first, second = self.add("첫째 주제", "첫째 키워드"), self.add("둘째 주제", "둘째 키워드")
        self.assertIn("후보 [2] 둘째 주제", self.ok("draft", "body", "2"))
        prefix = second.candidate.candidate_id[:6]
        self.assertIn("후보 [2] 둘째 주제", self.ok("draft", "body", prefix))
        self.assertIn("후보 [1] 첫째 주제", self.ok("draft", "body", first.candidate.candidate_id))
        self.assertEqual(self.data("draft", "body", "2")["candidate"]["ordinal"], 2)

    def test_a_missing_or_ambiguous_candidate_is_the_same_error_as_the_candidates_command(self):
        self.add("가", "가 키워드")
        err = self.fails("draft", "body", "5")
        self.assertIn("CANDIDATE_NOT_FOUND", err)
        self.assertIn("후보는 1개뿐", err)
        for text in ("abcd", "zzzz1234", "ab"):
            self.assertIn("CANDIDATE_NOT_FOUND", self.fails("draft", "body", text))
        with self.ctx.store() as store:
            for index, base in enumerate(("ab12cd34" + "0" * 24, "ab12cd35" + "0" * 24)):
                store.save_candidate(cd.Candidate.new(f"겹침 {index}", f"겹침 키워드 {index}", ("naver_a",), candidate_id=base, now=f"2026-11-02T03:00:0{index + 2}Z"))
        self.assertIn("CANDIDATE_AMBIGUOUS", self.fails("draft", "body", "ab12"))

    def test_rejected_candidates_get_a_body_with_a_note_and_stay_rejected(self):
        self.add()
        svc.move_candidate(self.ctx, "1", cd.REJECTED)
        data = self.data("draft", "body", "1")
        self.assertTrue([note for note in data["notes"] if "‘제외’ 상태" in note])
        self.assertEqual(svc.show_candidate(self.ctx, "1").row.candidate.status, cd.REJECTED)


class BlogChoiceTest(Base):
    def test_an_explicit_naver_blog_inside_the_recommendation_has_no_note(self):
        self.add(blogs=("naver_a", "naver_b"))
        data = self.data("draft", "body", "1", "--blog", "naver_b")
        self.assertEqual((data["body"]["blog"], data["notes"]), ("naver_b", []))

    def test_a_naver_blog_outside_the_recommendation_is_followed_with_a_note(self):
        self.add(blogs=("naver_a",))
        data = self.data("draft", "body", "1", "--blog", "naver_b")
        self.assertEqual(data["body"]["blog"], "naver_b")
        self.assertTrue([note for note in data["notes"] if "네이버 B 은(는) 이 후보의 추천 대상 블로그(네이버 A)가 아니지만 요청대로" in note])

    def test_without_a_blog_the_selected_naver_blog_wins_over_the_recommendation(self):
        self.add(blogs=("naver_a", "naver_b"))
        svc.select_candidate(self.ctx, "1", "naver_b")
        data = self.data("draft", "body", "1")
        self.assertEqual((data["body"]["blog"], data["notes"]), ("naver_b", []))

    def test_without_a_blog_and_with_several_choices_the_first_naver_is_used_and_the_rest_are_named(self):
        self.add(blogs=("naver_a", "naver_b"))
        data = self.data("draft", "body", "1")
        self.assertEqual(data["body"]["blog"], "naver_a")
        self.assertIn("대상 블로그를 정하지 않아 추천 대상 블로그 중 첫 번째인 네이버 A 용으로 만들었습니다", data["notes"][0])
        self.assertIn("네이버 B", data["notes"][0])

    def test_a_candidate_for_github_and_naver_gets_the_naver_blog_and_a_note(self):
        self.add(blogs=("github_pages", "naver_b", "naver_a"))
        data = self.data("draft", "body", "1")
        self.assertEqual(data["body"]["blog"], "naver_b")
        self.assertIn("네이버 블로그 중 첫 번째인 네이버 B 용으로 만들었습니다", data["notes"][0])
        self.assertIn("네이버 A", data["notes"][0])
        self.add(topic="하나만", keyword="하나만 키워드", blogs=("github_pages", "naver_a"))
        data = self.data("draft", "body", "2")
        self.assertEqual(data["body"]["blog"], "naver_a")
        self.assertNotIn("다른 블로그용은", data["notes"][0])

    def test_a_blog_that_is_not_naver_is_refused_with_an_easy_error(self):
        self.add(blogs=("github_pages",))
        for blog in ("github_pages", "blogger_ko", "blogger_en"):
            err = self.fails("draft", "body", "1", "--blog", blog)
            self.assertIn("DRAFT_OPTION_INVALID", err)
            self.assertIn("네이버 블로그(naver_a·naver_b)용만", err)
        err = self.fails("draft", "body", "1")
        self.assertIn("DRAFT_OPTION_INVALID", err)
        self.assertIn("네이버 블로그", err)

    def test_an_unknown_blog_is_a_usage_error(self):
        self.add()
        code, out, err = self.run_cli("draft", "body", "1", "--blog", "tistory")
        self.assertEqual((code, out), (2, ""))
        self.assertIn("사용법 오류", err)
        self.assertNotIn("tistory", err)

    def test_the_text_output_prints_the_note_that_says_how_the_blog_was_chosen(self):
        self.add(blogs=("naver_a", "naver_b"))
        out = self.ok("draft", "body", "1")
        self.assertIn("참고: 대상 블로그를 정하지 않아 추천 대상 블로그 중 첫 번째인 네이버 A 용으로 만들었습니다", out)
        self.assertNotIn("참고:", self.ok("draft", "body", "1", "--blog", "naver_a"))

    def test_choose_naver_blog_directly(self):
        candidate = cd.Candidate.new("주제", "키워드", ("blogger_ko", "naver_b", "naver_a"), now="2026-11-02T03:00:00Z")
        self.assertEqual(draft_body.choose_naver_blog(candidate, None)[0], "naver_b")
        self.assertEqual(draft_body.choose_naver_blog(candidate, "naver_a")[0], "naver_a")
        with self.assertRaises(Exception) as caught:
            draft_body.choose_naver_blog(candidate, "tistory")
        self.assertEqual(caught.exception.code, "DRAFT_OPTION_INVALID")
        with self.assertRaises(Exception) as caught:
            draft_body.choose_naver_blog(candidate, "blogger_ko")
        self.assertEqual(caught.exception.code, "DRAFT_OPTION_INVALID")
        only = cd.Candidate.new("주제", "키워드", ("blogger_ko",), now="2026-11-02T03:00:00Z")
        with self.assertRaises(Exception) as caught:
            draft_body.choose_naver_blog(only, None)
        self.assertEqual(caught.exception.code, "DRAFT_OPTION_INVALID")


class ProfileTest(Base):
    def test_the_naver_profile_values_are_applied(self):
        self.add(blogs=("naver_a",), sub_keywords=("청소기 추천",))
        self.ctx.settings.save_naver_profile(NaverProfile("naver_a", "에이", "https://blog.naver.com/exampleaaa", audience="초보 집주인", default_tags=("생활",), max_tags=3, categories=(("무선 청소기", "생활정보"),),
                                                          tone="정중한 합니다체", ending_style="체크리스트로 마무리"))
        data = self.data("draft", "body", "1", "--blog", "naver_a")
        body = data["body"]
        self.assertTrue(data["profile_found"])
        self.assertEqual((body["audience"], body["category"], len(body["tags"]), body["style"]), ("초보 집주인", "생활정보", 3, "hapsyo"))
        self.assertIn("확인 항목은", body["body_text"])

    def test_the_channel_profile_values_are_applied_and_beat_the_naver_profile(self):
        self.add(blogs=("naver_a",))
        self.ctx.settings.save_naver_profile(NaverProfile("naver_a", "에이", "https://blog.naver.com/exampleaaa", audience="프로필 독자", tone="정중한 합니다체"))
        self.write_channels(tone="친근한 해요체", audience="채널 독자", categories=("가전 고르기", "디지털 기기"), monetization_focus=("small_appliance",))
        data = self.data("draft", "body", "1", "--blog", "naver_a")
        body = data["body"]
        self.assertTrue(data["channel_found"])
        self.assertEqual((body["audience"], body["category"], body["style"], body["sponsor_slot"]), ("채널 독자", "가전 고르기", "haeyo", True))
        self.assertTrue(any("협찬" in text for text in body["checks"]))

    def test_the_channel_exclude_keywords_field_is_not_read_because_the_screen_says_it_is_saved_only(self):
        """채널 프로필의 제외 키워드 칸은 화면이 '지금은 저장만 된다' 고 말하는 칸이다(D-241) — 본문 생성은 그 칸을 읽지 않으므로 칸을 채워도 글이 그대로다(읽게 하려면 화면 문구와 이 시험을 함께 고친다)."""
        self.add(blogs=("naver_a",))
        before = self.data("draft", "body", "1", "--blog", "naver_a")["body"]
        self.write_channels(exclude_keywords=("공식",))
        body = self.data("draft", "body", "1", "--blog", "naver_a")["body"]
        self.assertIn("공식", body["body_text"])
        self.assertEqual(body["plain_text"], before["plain_text"])
        self.assertEqual(body["dropped"], 0)

    def test_missing_profiles_are_notes_and_the_exit_code_is_still_zero(self):
        self.add(blogs=("naver_a",))
        out = self.ok("draft", "body", "1", "--blog", "naver_a")
        self.assertIn("이 네이버 블로그의 프로필이 아직 없어 공통 기본값으로 만들었습니다", out)
        data = self.data("draft", "body", "1", "--blog", "naver_a")
        self.assertFalse(data["profile_found"])
        self.assertFalse(data["channel_found"])
        self.assertEqual(data["body"]["style"], "haeyo")

    def test_a_broken_settings_file_is_reported_and_not_hidden(self):
        self.add(blogs=("naver_a",))
        self.ctx.workspace.settings_path.write_text("{ 깨진 설정", encoding="utf-8")
        before = self.snapshot()
        err = self.fails("draft", "body", "1", "--blog", "naver_a")
        self.assertIn("SETTINGS_INVALID", err)
        self.assertEqual(self.snapshot(), before)

    def test_a_broken_channel_file_is_reported_and_not_hidden_and_not_overwritten(self):
        self.add(blogs=("naver_a",))
        path = tf.topic_paths(self.ctx.workspace).profiles
        path.parent.mkdir(parents=True)
        path.write_text("깨진 파일", encoding="utf-8")
        before = self.snapshot()
        err = self.fails("draft", "body", "1", "--blog", "naver_a")
        self.assertIn("TOPIC_FILE_INVALID", err)
        self.assertEqual(self.snapshot(), before)
        write_json(path, {"schema": 2, "profiles": []})
        before = self.snapshot()
        err = self.fails("draft", "body", "1", "--blog", "naver_a")
        self.assertIn("CONTENT_INVALID", err)
        self.assertEqual(self.snapshot(), before)

    def test_the_default_channel_profile_is_used_when_the_file_is_missing_and_marks_a_sponsor_area(self):
        self.add(blogs=("naver_a",))
        data = self.data("draft", "body", "1", "--blog", "naver_a")
        self.assertFalse(data["channel_found"])
        self.assertTrue(data["body"]["sponsor_slot"])                              # 기본 채널 프로필(네이버 A)의 우선 수익화 분야에 소형가전이 있다
        self.assertEqual(data["body"]["domain"], "appliance")


class OptionsAndOutputTest(Base):
    def test_every_option_flows_into_the_body_and_the_json_lists_what_was_used(self):
        self.add(blogs=("naver_a",))
        data = self.data("draft", "body", "1", "--blog", "naver_a", "--message", "전하고 싶은 말이에요.", "--experience", "지난달부터 써 왔어요.", "--opinion", "의견이에요.", "--must-include", "넣을 문장이에요.",
                         "--exclude", "광고,가격", "--audience", "신혼부부", "--title-direction", "질문형으로", "--url", "https://example.com/a", "--price-date", "값 하나", "--conclusion", "결론이에요.")
        body = data["body"]
        for text in ("전하고 싶은 말이에요.", "지난달부터 써 왔어요.", "의견이에요.", "넣을 문장이에요.", "결론이에요.", "https://example.com/a", "값 하나"):
            self.assertIn(text, body["body_text"])
        self.assertEqual(set(body["used"]), {"message", "experience", "opinion", "must_include", "price_date", "conclusion", "urls"})
        self.assertEqual(body["audience"], "신혼부부")
        self.assertEqual(data["options"]["audience"], "신혼부부")

    def test_the_text_output_is_a_readable_korean_page_with_the_copyable_text_in_the_middle(self):
        self.add(blogs=("naver_a",), sub_keywords=("청소기 추천",))
        out = self.ok("draft", "body", "1", "--blog", "naver_a")
        data = self.data("draft", "body", "1", "--blog", "naver_a")
        self.assertIn("초안 본문 — 후보 [1] 무선 청소기 선택 기준 · 네이버 A 용", out)
        self.assertIn("AI 를 쓰지 않았고 아무것도 저장하지 않았습니다", out)
        self.assertIn(data["body"]["plain_text"], out)
        self.assertIn("제목 후보:", out)
        self.assertIn("선택한 제목: " + data["body"]["selected_title"], out)
        for label in ("핵심 키워드:", "보조 키워드:", "추천 태그:", "추천 카테고리:", "한 줄 요약:", "확인 권장(있어도 초안은 이대로 복사해 쓸 수 있습니다):"):
            self.assertIn(label, out)
        self.assertIn("정하지 못했습니다", out)
        self.assertNotIn("만든 방법:", out)
        for word in ENGLISH:
            self.assertNotIn(word, out)
        self.assertIsNone(STATUS_CODES.search(out))
        self.assertIsNone(LONG_ID.search(out))
        self.assertNotIn("Traceback", out)
        self.assertEqual(claims.find_claims(data["body"]["plain_text"]), ())

    def test_verbose_adds_how_it_was_made(self):
        self.add(blogs=("naver_a",))
        out = self.ok("draft", "body", "1", "--blog", "naver_a", "--verbose")
        self.assertIn("만든 방법: 분야 생활가전", out)
        self.assertIn("네이버 프로필 없음", out)
        self.assertIn("채널 프로필 기본값", out)

    def test_the_type_option_sets_the_post_type_and_a_wrong_type_is_an_easy_error(self):
        self.add(blogs=("naver_a",))
        data = self.data("draft", "body", "1", "--blog", "naver_a", "--type", "비교형")
        self.assertEqual(data["body"]["post_type"], "비교형")
        self.assertIn("글 유형: 문제 해결형", self.ok("draft", "body", "1", "--blog", "naver_a", "--type", "문제 해결형"))
        err = self.fails("draft", "body", "1", "--blog", "naver_a", "--type", "없는 유형")
        self.assertIn("DRAFT_OPTION_INVALID", err)

    def test_the_text_output_names_the_tone_the_text_was_written_in(self):
        self.add(blogs=("naver_a",))
        self.assertIn("말투 해요체", self.ok("draft", "body", "1", "--blog", "naver_a"))
        self.write_channels(tone="정중한 합니다체")
        self.assertIn("말투 합니다체", self.ok("draft", "body", "1", "--blog", "naver_a"))
        self.assertEqual(self.data("draft", "body", "1", "--blog", "naver_a")["body"]["style"], "hapsyo")

    def test_a_replaced_review_candidate_says_so_and_has_no_review_words(self):
        self.add(topic="서울 맛집 방문 후기", keyword="맛집 방문 후기", blogs=("naver_a",), post_type="장소·업체 정보형")
        out = self.ok("draft", "body", "1", "--blog", "naver_a")
        self.assertIn("후보의 ‘방문 후기’ 형식은", out)
        data = self.data("draft", "body", "1", "--blog", "naver_a")
        self.assertNotIn("후기", data["body"]["plain_text"])

    def test_json_has_the_documented_shape_and_masks_nothing_it_should_not(self):
        self.add(blogs=("naver_a",))
        payload = json.loads(self.ok("--json", "draft", "body", "1", "--blog", "naver_a"))
        self.assertEqual((payload["ok"], payload["command"]), (True, "draft body"))
        self.assertEqual(set(payload["data"]), {"read_only", "candidate", "body", "options", "notes", "profile_found", "channel_found"})
        self.assertTrue(payload["data"]["read_only"])
        self.assertEqual(payload["data"]["candidate"]["ordinal"], 1)
        self.assertTrue(4 <= len([block for block in payload["data"]["body"]["blocks"] if block["kind"] in ("section", "experience")]) <= 6)

    def test_wrong_input_values_exit_with_one_and_say_which_field(self):
        self.add(blogs=("naver_a",))
        for args, field in ((("--url", "http://example.com/a"), "참고 URL"), (("--length", "많이"), "원하는 글 길이"), (("--message", "가" * 501), "직접 전달하고 싶은 내용"), (("--price-date", "x" * 101), "실제 가격이나 날짜")):
            err = self.fails("draft", "body", "1", "--blog", "naver_a", *args)
            with self.subTest(args=args):
                self.assertIn("DRAFT_OPTION_INVALID", err)
                self.assertIn(field, err)
        self.assertEqual(self.snapshot().keys(), {"chanceblog.db"})

    def test_a_key_shaped_input_is_refused_and_never_printed(self):
        self.add(blogs=("naver_a",))
        for option in ("--message", "--experience", "--opinion", "--conclusion", "--audience", "--title-direction", "--must-include", "--exclude", "--price-date"):
            code, out, err = self.run_cli("draft", "body", "1", "--blog", "naver_a", option, "내용은 " + KEY + " 입니다")
            with self.subTest(option=option):
                self.assertEqual((code, out), (1, ""))
                self.assertNotIn(KEY, out + err)
                self.assertIn("DRAFT_OPTION_INVALID", err)

    def test_a_key_shaped_candidate_keyword_stops_the_body_and_the_key_is_not_printed(self):
        with self.ctx.store() as store:
            store.save_candidate(cd.Candidate.new("정상 주제", "정상 키워드 " + KEY, ("naver_a",), now="2026-11-02T03:00:01Z"))
        code, out, err = self.run_cli("draft", "body", "1", "--blog", "naver_a")
        self.assertEqual((code, out), (1, ""))
        self.assertNotIn(KEY, out + err)
        self.assertIn("CONTENT_INVALID", err)
        self.assertIn("후보의 핵심 키워드", err)
        code, out, err = self.run_cli("--json", "draft", "body", "1", "--blog", "naver_a")
        self.assertEqual(code, 1)
        self.assertNotIn(KEY, out + err)
        self.assertEqual(json.loads(out)["error"]["code"], "CONTENT_INVALID")

    def test_a_long_random_run_in_an_option_is_refused_like_the_plan_does(self):
        self.add(blogs=("naver_a",))
        long_run = "a1" * 20
        err = self.fails("draft", "body", "1", "--blog", "naver_a", "--message", f"번호는 {long_run} 입니다")
        self.assertIn("DRAFT_OPTION_INVALID", err)
        self.assertNotIn(long_run, err)
        plan_err = self.fails("draft", "plan", "1", "--blog", "naver_a", "--message", f"번호는 {long_run} 입니다")
        self.assertIn("DRAFT_OPTION_INVALID", plan_err)

    def test_usage_errors_exit_with_two(self):
        self.add()
        code, out, err = self.run_cli("draft", "body")
        self.assertEqual((code, out), (2, ""))
        self.assertIn("사용법 오류", err)
        code, out, err = self.run_cli("draft", "body", "1", "--모르는옵션")
        self.assertEqual((code, out), (2, ""))
        code, out, err = self.run_cli("draft")
        self.assertEqual((code, out), (2, ""))

    def test_help_is_korean_and_the_two_commands_share_the_eleven_input_options(self):
        help_texts = {}
        for name in ("plan", "body"):
            code, out, err = self.run_cli("draft", name, "--help")
            self.assertEqual((code, err), (0, ""))
            for word in ENGLISH:
                self.assertNotIn(word, out)
            help_texts[name] = set(re.findall("--[a-z]+(?:-[a-z]+)*", out))
        self.assertTrue(INPUT_OPTIONS <= help_texts["plan"])
        self.assertTrue(INPUT_OPTIONS <= help_texts["body"])
        self.assertEqual(help_texts["plan"], help_texts["body"])
        code, out, err = self.run_cli("draft", "--help")
        self.assertIn("body", out)
        self.assertIn("plan", out)
        self.assertIn("draft body", out)

    def test_every_output_line_goes_through_the_mask(self):
        self.add(blogs=("naver_a",))
        with mock.patch.object(cli, "mask_block", wraps=cli.mask_block) as spy:
            self.ok("draft", "body", "1", "--blog", "naver_a")
        self.assertTrue(spy.called)


class ServiceFunctionTest(Base):
    def test_make_body_returns_a_frozen_result_with_the_row_options_and_flags(self):
        self.add(blogs=("naver_a",))
        result = draft_body.make_body(self.ctx, "1", blog="naver_a", options=DraftOptions(message="전하는 말이에요."))
        self.assertEqual(result.row.ordinal, 1)
        self.assertEqual(result.options.message, "전하는 말이에요.")
        self.assertFalse(result.profile_found)
        self.assertFalse(result.channel_found)
        with self.assertRaises(Exception):
            result.notes = ()
        self.assertEqual(result.to_dict()["body"], result.body.to_dict())
        lines = draft_body.body_lines(result)
        self.assertEqual(lines[0].split(" — ")[0], "초안 본문")
        self.assertIn(result.body.plain_text, "\n".join(lines))

    def test_the_service_never_writes_by_its_source(self):
        import ast
        source = (Path(__file__).resolve().parent.parent / "src" / "chanceblog_desktop" / "service" / "draft_body.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        names = {node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "") for node in ast.walk(tree) if isinstance(node, ast.Call)}
        self.assertFalse(names & {"write_text", "write_bytes", "write", "open", "unlink", "mkdir", "replace", "rename", "remove", "rmtree", "write_json", "save_slot", "save_naver_profile", "save_seeds", "touch"})
        imported = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        self.assertNotIn("context", {(module or "").split(".")[-1] for module in imported} - {"candidates"})

    def test_body_lines_for_a_candidate_without_a_category_or_tags_do_not_crash(self):
        self.add(topic="독서 습관", keyword="독서 습관", blogs=("naver_b",))
        out = self.ok("draft", "body", "1")
        self.assertIn("네이버 B 용", out)


class SafetyScreenTest(Base):
    """독립 검증 H2 — 엔진이 자동 초안 중지로 판정하는 후보는 본문 초안을 만들지 않고, 근거 확인 필요 단계는 확인 권장 맨 위에 경고를 둔다. `draft plan` 은 그대로다."""
    STOPPED = ("당뇨 완치 영양제", "다이어트 즉시 효과", "아토피 확실한 치료", "체중 감량 무조건 성공")

    def test_the_four_stopped_candidates_get_no_body_and_the_error_does_not_repeat_what_was_typed(self):
        for keyword in self.STOPPED:
            self.add(topic=f"{keyword} 정리", keyword=keyword, blogs=("naver_a",))
        before = self.snapshot()
        for number, keyword in enumerate(self.STOPPED, 1):
            with self.subTest(keyword=keyword):
                code, out, err = self.run_cli("draft", "body", str(number), "--blog", "naver_a")
                self.assertEqual((code, out), (1, ""))
                self.assertIn("CONTENT_INVALID", err)
                self.assertIn("자동 초안 중지", err)
                self.assertIn("후보 보기", err)
                self.assertNotIn("Traceback", err)
                code2, out2, err2 = self.run_cli("--json", "draft", "body", str(number), "--blog", "naver_a")
                self.assertEqual(code2, 1)
                self.assertEqual(json.loads(out2)["error"]["code"], "CONTENT_INVALID")
                for text in (err, out2, err2):
                    for word in keyword.split():
                        self.assertNotIn(word, text)                                # 입력한 글(제목·키워드)을 오류에 되풀이하지 않는다
        self.assertEqual(self.snapshot(), before)                                    # 거절해도 아무것도 쓰지 않는다

    def test_the_engine_is_asked_with_the_texts_it_uses_for_a_candidate_and_the_same_report_reaches_the_generator(self):
        self.add(topic="영양제 고르는 기준 안내", keyword="영양제 고르는 기준", blogs=("naver_a",), sub_keywords=("비타민 선택", "유산균 비교"))
        with mock.patch.object(safety, "check_text", wraps=safety.check_text) as asked, mock.patch.object(content_body, "build_body", wraps=content_body.build_body) as built:
            self.ok("draft", "body", "1", "--blog", "naver_a")
        asked.assert_called_once_with(["영양제 고르는 기준 안내", "영양제 고르는 기준", "비타민 선택", "유산균 비교"])
        self.assertIsInstance(built.call_args.kwargs["safety"], safety.SafetyReport)
        self.assertEqual(built.call_args.kwargs["safety"].stage, safety.STAGE_MARK)

    def test_a_stopped_candidate_is_refused_before_the_blog_or_the_profile_files_are_looked_at(self):
        self.add(topic="다이어트 즉시 효과 정리", keyword="다이어트 즉시 효과", blogs=("github_pages",))
        err = self.fails("draft", "body", "1")                                       # 네이버가 아닌 블로그라 다른 이유로도 거절될 후보 — 안전 판정이 먼저다
        self.assertIn("CONTENT_INVALID", err)
        self.assertNotIn("DRAFT_OPTION_INVALID", err)

    def test_draft_plan_is_unchanged_and_still_makes_a_plan_for_a_stopped_candidate(self):
        self.add(topic="다이어트 즉시 효과 정리", keyword="다이어트 즉시 효과", blogs=("naver_a",))
        out = self.ok("draft", "plan", "1", "--blog", "naver_a")
        self.assertIn("다이어트", out)
        self.assertEqual(self.data("draft", "plan", "1", "--blog", "naver_a")["read_only"], True)

    def test_a_candidate_at_the_evidence_stage_gets_a_body_with_the_warning_on_top_and_the_health_paragraph(self):
        for keyword in ("당뇨 관리", "탈모 치료 효과", "콜레스테롤 낮추기"):
            self.add(topic=f"{keyword} 안내", keyword=keyword, blogs=("naver_a",))
        for number, keyword in enumerate(("당뇨 관리", "탈모 치료 효과", "콜레스테롤 낮추기"), 1):
            body = self.data("draft", "body", str(number), "--blog", "naver_a")["body"]
            with self.subTest(keyword=keyword):
                self.assertEqual(safety.check_text([f"{keyword} 안내", keyword]).stage, safety.STAGE_EVIDENCE)
                self.assertEqual(body["checks"][0], content_body.EVIDENCE_NOTE)
                self.assertEqual(body["sensitive"], "health")
                self.assertTrue(any("전문가" in paragraph for block in body["blocks"] if block["kind"] == "cautions" for paragraph in block["paragraphs"]))
        out = self.ok("draft", "body", "1", "--blog", "naver_a")
        self.assertIn("확인 권장(있어도 초안은 이대로 복사해 쓸 수 있습니다):" + chr(10) + "  - " + content_body.EVIDENCE_NOTE, out)

    def test_a_superlative_keyword_gets_the_assertion_warning_on_top_in_the_text_and_the_json(self):
        self.add(topic="최고의 청소기 비교", keyword="최고의 청소기", blogs=("naver_a",))
        body = self.data("draft", "body", "1", "--blog", "naver_a")["body"]
        self.assertIn("‘최고’", body["checks"][0])
        self.assertIn("본문 곳곳에 그대로 되풀이됩니다", body["checks"][0])
        self.assertIn("확인 권장(있어도 초안은 이대로 복사해 쓸 수 있습니다):" + chr(10) + "  - 후보의 제목·키워드에 단정·최상급·효과를 말하는 표현(‘최고’)", self.ok("draft", "body", "1", "--blog", "naver_a"))

    def test_a_sponsor_word_in_the_candidate_gets_the_sponsor_word_warning(self):
        self.add(topic="협찬 청소기 정리", keyword="협찬 청소기", blogs=("naver_a",))
        body = self.data("draft", "body", "1", "--blog", "naver_a")["body"]
        self.assertEqual(body["checks"][0], content_body.SPONSOR_WORD_NOTE)

    def test_a_candidate_with_nothing_to_warn_about_has_no_extra_line_and_the_basic_note_stays_first(self):
        self.add(blogs=("naver_a",))
        body = self.data("draft", "body", "1", "--blog", "naver_a")["body"]
        self.assertIn("본문은 입력하신 내용과 일반적인 확인 순서만으로 만든 기본 글입니다", body["checks"][0])
        self.assertEqual(safety.check_text(["무선 청소기 선택 기준", "무선 청소기"]).stage, safety.STAGE_GENERAL)

    def test_screen_returns_the_report_for_an_ordinary_candidate_and_raises_for_a_stopped_one(self):
        ordinary = cd.Candidate.new("무선 청소기 선택 기준", "무선 청소기", ("naver_a",), now="2026-11-02T03:00:00Z")
        self.assertFalse(draft_body.screen(ordinary).stop)
        stopped = cd.Candidate.new("다이어트 즉시 효과 정리", "다이어트 즉시 효과", ("naver_a",), now="2026-11-02T03:00:00Z")
        with self.assertRaises(Exception) as caught:
            draft_body.screen(stopped)
        self.assertEqual(caught.exception.code, "CONTENT_INVALID")
        self.assertNotIn("다이어트", str(caught.exception) + caught.exception.detail + caught.exception.rendered().message)

    def test_the_service_source_calls_the_engine_check_and_no_new_error_code_was_made(self):
        import ast
        source = (Path(__file__).resolve().parent.parent / "src" / "chanceblog_desktop" / "service" / "draft_body.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        called = {node.func.attr for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
        self.assertIn("check_text", called)
        codes = {node.args[0].value for node in ast.walk(tree) if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "AppError" and node.args and isinstance(node.args[0], ast.Constant)}
        self.assertEqual(codes, {"DRAFT_OPTION_INVALID", "CONTENT_INVALID"})


class KeyShapeServiceTest(Base):
    """독립 검증 M3 — 후보의 어느 칸에 있어도 키 모양 11종은 본문 명령에서 거절되고 출력(글·JSON·오류)에 나오지 않는다. 가짜 키 형식 문자열은 실행 중 조각을 이어 붙여 만든다."""
    SHAPES = {
        "구글형": "AI" + "za" + "B" * 35, "AQ형": "AQ" + "." + "C" * 20, "GOCSPX형": "GOC" + "SPX-" + "D" * 20, "1//0형": "1/" + "/0" + "E" * 20, "ya29형": "ya" + "29." + "F" * 20,
        "gh형": "gh" + "p_" + "G" * 36, "깃허브세분화형": "github" + "_pat_" + "H" * 30, "slack형": "xo" + "xb-" + "1234567890-" + "I" * 10, "AWS형": "AK" + "IA" + "J" * 16, "sk형": "s" + "k-" + "K" * 40,
        "해시32형": "a1b2" * 8,
    }

    def test_all_eleven_shapes_in_a_candidate_keyword_topic_or_sub_keyword_are_refused_and_never_printed(self):
        count = 0
        for name, shape in self.SHAPES.items():
            run = max(set(shape), key=shape.count) * 8
            for field in ("keyword", "topic", "sub"):
                folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
                self.addCleanup(folder.cleanup)
                ctx = ss.make_ctx(Path(folder.name), repo="")
                fields = {"keyword": "정상 키워드", "topic": "정상 주제", "sub_keywords": ()}
                if field == "sub":
                    fields["sub_keywords"] = (shape,)
                else:
                    fields[field] = shape
                with ctx.store() as store:
                    store.save_candidate(cd.Candidate.new(fields["topic"], fields["keyword"], ("naver_a",), sub_keywords=fields["sub_keywords"], now="2026-11-02T03:00:01Z"))
                for argv in (("draft", "body", "1", "--blog", "naver_a"), ("--json", "draft", "body", "1", "--blog", "naver_a")):
                    code, out, err = ss.run_cli(ctx, *argv)
                    count += 1
                    with self.subTest(shape=name, field=field, json=argv[0] == "--json"):
                        self.assertEqual(code, 1, (out + err)[:300])
                        for text in (out, err):
                            self.assertNotIn(shape, text)
                            self.assertNotIn(run, text)
                        self.assertIn("CONTENT_INVALID", out + err)
        self.assertEqual(count, 11 * 3 * 2)


class ProcessTest(unittest.TestCase):
    def test_a_real_process_prints_the_body_and_writes_nothing(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            ctx = ss.make_ctx(tmp, repo="")
            ctx.clock.advance(seconds=1)
            svc.add_candidate(ctx, topic="무선 청소기 선택 기준", keyword="무선 청소기", blogs=("naver_a",), sub_keywords=("청소기 추천",))
            root = ctx.workspace.root
            before = ss.tree_snapshot(root)
            env = dict(os.environ, PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=str(Path(__file__).resolve().parent.parent / "src"))
            env.pop("CHANCEBLOG_LOCAL_REPO", None)
            done = subprocess.run([sys.executable, "-X", "utf8", "-m", "chanceblog_desktop", "--data-dir", str(root), "draft", "body", "1", "--blog", "naver_a"], capture_output=True, text=True, env=env, timeout=120,
                                  encoding="utf-8")
            self.assertEqual((done.returncode, done.stderr), (0, ""), done.stdout[-400:])
            self.assertIn("초안 본문 — 후보 [1] 무선 청소기 선택 기준", done.stdout)
            self.assertIn("복사용 글(제목 + 본문)", done.stdout)
            self.assertEqual(ss.tree_snapshot(root), before)


if __name__ == "__main__":
    unittest.main()
