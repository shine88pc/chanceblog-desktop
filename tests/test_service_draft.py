"""명령줄 `draft plan` 과 서비스 함수(`service/draft.py`) 시험 — 같은 프로세스에서 돌린다(진짜 프로세스 시험은 test_service_draft_process.py).

지키는 것:
  1) **읽기만 한다** — 보관함·설정·데이터 폴더를 만들지도 바꾸지도 않는다(파일 바이트 그대로, 옛 구조 파일도 올리지 않는다, 보관함을 읽기 전용으로 연다). 네트워크·git·배포 확인을 쓰지 않는다.
  2) 후보 번호는 `candidates` 명령과 같은 규칙(순번·번호 앞 4자 이상, 없으면 CANDIDATE_NOT_FOUND, 겹치면 CANDIDATE_AMBIGUOUS). 선택 입력은 하나도 없어도 종료 코드 0 이다.
  3) 대상 블로그: `--blog` > 그 후보를 고른 블로그(첫 번째) > 추천 대상 블로그(첫 번째). 추천 밖의 블로그·여럿 중 하나를 정한 것은 안내한다. 네이버 프로필이 없으면 멈추지 않고 알린다. 설정 파일이 깨졌으면 숨기지 않는다.
  4) 후보가 네이버 A·B 둘 다를 대상으로 하면 다른 블로그용 계획과 견준다. 출력은 쉬운 한국어 표(영문 상태 코드·긴 번호 없음, 값이 온 곳은 `--verbose`·`--json` 에서만)이고 `--json` 은 `ok/command/data`.
  5) 틀린 입력 값은 종료 코드 1(`DRAFT_OPTION_INVALID`, 어느 칸이 왜 안 되는지), 사용법 오류는 2, 화면에 나가는 모든 글에서 키 모양 문자열은 가려진다.
"""
import json
import re
import socket
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import service_support as ss  # noqa: E402
import store_v1  # noqa: E402

from chanceblog_desktop.content import candidates as cd  # noqa: E402
from chanceblog_desktop.content.draft_options import DraftOptions  # noqa: E402
from chanceblog_desktop.content.profiles import NaverProfile  # noqa: E402
from chanceblog_desktop.content.store import Store  # noqa: E402
from chanceblog_desktop.service import candidates as svc  # noqa: E402
from chanceblog_desktop.service import cli, draft  # noqa: E402

ENGLISH = ("usage:", "positional arguments", "options:", "optional arguments", "show this help message and exit")
STATUS_CODES = re.compile(r"\b(?:NEW|REVIEW|SELECTED|HOLD|REJECTED)\b")
LONG_ID = re.compile(r"\b[0-9a-f]{32}\b")
EXPERIENCE = "지난달부터 이 제품을 써 왔고 배터리는 하루 종일 갔습니다."


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

    def error_json(self, *argv):
        code, out, err = self.run_cli("--json", *argv)
        self.assertEqual((code, err), (1, ""), (argv, out, err))
        payload = json.loads(out)
        self.assertFalse(payload["ok"])
        return payload

    def add(self, topic="겨울 보일러 점검 순서", keyword="보일러 점검", blogs=("naver_a",), **fields):
        self.ctx.clock.advance(seconds=1)
        return svc.add_candidate(self.ctx, topic=topic, keyword=keyword, blogs=blogs, **fields).row

    def snapshot(self):
        return ss.tree_snapshot(self.root) if self.root.exists() else None


class ReadOnlyTest(Base):
    def test_without_a_store_it_says_the_candidate_is_missing_and_creates_nothing(self):
        err = self.fails("draft", "plan", "1")
        self.assertIn("CANDIDATE_NOT_FOUND", err)
        self.assertFalse(self.root.exists())
        payload = self.error_json("draft", "plan", "1")
        self.assertEqual((payload["command"], payload["error"]["code"]), ("draft plan", "CANDIDATE_NOT_FOUND"))
        self.assertFalse(self.root.exists())

    def test_a_plan_changes_no_file_in_the_data_folder_and_creates_no_settings_or_backup(self):
        self.add(sub_keywords=("보일러 청소",))
        before = self.snapshot()
        self.assertEqual(set(before), {"chanceblog.db"})
        self.ok("draft", "plan", "1", "--blog", "naver_a")
        self.ok("draft", "plan", "1", "--blog", "naver_a", "--experience", EXPERIENCE, "--url", "https://example.com/a", "--length", "2500+")
        self.data("draft", "plan", "1")
        self.assertEqual(self.snapshot(), before)

    def test_with_profiles_saved_the_settings_file_is_read_and_not_rewritten(self):
        self.add(blogs=("naver_a", "naver_b"))
        ss.naver_profiles(self.ctx)
        before = self.snapshot()
        self.assertIn("settings.json", before)
        self.ok("draft", "plan", "1", "--blog", "naver_a")
        self.ok("draft", "plan", "1", "--blog", "naver_b")
        self.assertEqual(self.snapshot(), before)

    def test_the_store_is_opened_read_only_and_never_written(self):
        self.add()
        opened = []
        original = Store.open.__func__

        def spy(cls, path, **kwargs):
            opened.append(kwargs)
            return original(cls, path, **kwargs)

        with mock.patch.object(Store, "open", classmethod(spy)):
            self.ok("draft", "plan", "1")
        self.assertTrue(opened)
        self.assertTrue(all(kwargs.get("migrate") is False for kwargs in opened), opened)

    def test_an_old_structure_file_is_not_upgraded_and_has_no_candidates(self):
        self.root.mkdir(parents=True)
        path = self.ctx.workspace.store_path
        store_v1.make_v1_file(path)
        before = self.snapshot()
        err = self.fails("draft", "plan", "1")
        self.assertIn("CANDIDATE_NOT_FOUND", err)
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(list(self.root.glob("*.bak")))

    def test_no_network_git_or_deploy_check_is_used(self):
        self.add(blogs=("naver_a", "naver_b"))
        ss.naver_profiles(self.ctx)
        with mock.patch.object(socket, "socket", side_effect=AssertionError("네트워크")), mock.patch.object(socket, "getaddrinfo", side_effect=AssertionError("이름 찾기")):
            self.ok("draft", "plan", "1", "--blog", "naver_a", "--url", "https://example.com/a")
        self.assertEqual(self.ctx.backend.calls, [])

    def test_the_candidate_and_its_status_are_unchanged(self):
        row = self.add()
        svc.select_candidate(self.ctx, "1", "naver_a")
        before = svc.show_candidate(self.ctx, "1").to_dict()
        self.ok("draft", "plan", "1", "--blog", "naver_a")
        self.assertEqual(svc.show_candidate(self.ctx, "1").to_dict(), before)
        self.assertEqual(before["candidate"]["status"], cd.SELECTED)
        self.assertEqual(row.candidate.status, cd.NEW)


class ResolveCandidateTest(Base):
    def test_ordinals_and_id_prefixes_choose_the_candidate(self):
        first, second = self.add("첫째 주제", "첫째 키워드"), self.add("둘째 주제", "둘째 키워드")
        self.assertIn("후보 [2] 둘째 주제", self.ok("draft", "plan", "2"))
        prefix = second.candidate.candidate_id[:6]
        self.assertIn("후보 [2] 둘째 주제", self.ok("draft", "plan", prefix))
        self.assertIn("후보 [1] 첫째 주제", self.ok("draft", "plan", first.candidate.candidate_id))
        self.assertEqual(self.data("draft", "plan", "2")["candidate"]["ordinal"], 2)

    def test_a_missing_or_ambiguous_candidate_is_the_same_error_as_the_candidates_command(self):
        self.add("가", "가 키워드")
        err = self.fails("draft", "plan", "5")
        self.assertIn("CANDIDATE_NOT_FOUND", err)
        self.assertIn("후보는 1개뿐", err)
        for text in ("abcd", "zzzz1234"):
            self.assertIn("CANDIDATE_NOT_FOUND", self.fails("draft", "plan", text))
        err = self.fails("draft", "plan", "ab")
        self.assertIn("CANDIDATE_NOT_FOUND", err)
        with self.ctx.store() as store:                                   # 같은 앞부분으로 시작하는 후보 둘
            for index, base in enumerate(("ab12cd34" + "0" * 24, "ab12cd35" + "0" * 24)):
                store.save_candidate(cd.Candidate.new(f"겹침 {index}", f"겹침 키워드 {index}", ("naver_a",), candidate_id=base, now=f"2026-11-02T03:00:0{index + 2}Z"))
        err = self.fails("draft", "plan", "ab12")
        self.assertIn("CANDIDATE_AMBIGUOUS", err)

    def test_rejected_candidates_get_a_plan_with_a_note_and_stay_rejected(self):
        self.add()
        svc.move_candidate(self.ctx, "1", cd.REJECTED)
        data = self.data("draft", "plan", "1")
        self.assertTrue([note for note in data["notes"] if "‘제외’ 상태" in note])
        self.assertEqual(svc.show_candidate(self.ctx, "1").row.candidate.status, cd.REJECTED)


class BlogChoiceTest(Base):
    def test_an_explicit_blog_inside_the_recommendation_has_no_note(self):
        self.add(blogs=("naver_a", "naver_b"))
        data = self.data("draft", "plan", "1", "--blog", "naver_b")
        self.assertEqual((data["plan"]["blog"], data["notes"]), ("naver_b", []))

    def test_a_blog_outside_the_recommendation_is_followed_with_a_note(self):
        self.add(blogs=("naver_a",))
        data = self.data("draft", "plan", "1", "--blog", "github_pages")
        self.assertEqual(data["plan"]["blog"], "github_pages")
        self.assertTrue([note for note in data["notes"] if "GitHub Pages 은(는) 이 후보의 추천 대상 블로그(네이버 A)가 아니지만 요청대로" in note])

    def test_without_a_blog_the_selected_blog_wins_over_the_recommendation(self):
        self.add(blogs=("naver_a", "naver_b"))
        svc.select_candidate(self.ctx, "1", "naver_b")
        data = self.data("draft", "plan", "1")
        self.assertEqual(data["plan"]["blog"], "naver_b")
        self.assertEqual(data["notes"], [])

    def test_without_a_blog_and_with_several_choices_the_first_is_used_and_the_rest_are_named(self):
        self.add(blogs=("naver_a", "naver_b"))
        data = self.data("draft", "plan", "1")
        self.assertEqual(data["plan"]["blog"], "naver_a")
        note = data["notes"][0]
        self.assertIn("대상 블로그를 정하지 않아 추천 대상 블로그 중 첫 번째인 네이버 A 용으로 만들었습니다", note)
        self.assertIn("네이버 B", note)
        svc.select_candidate(self.ctx, "1", "naver_b")
        svc.select_candidate(self.ctx, "1", "naver_a")
        data = self.data("draft", "plan", "1")
        self.assertEqual(data["plan"]["blog"], "naver_a")
        self.assertIn("고른 블로그 중 첫 번째", data["notes"][0])

    def test_a_single_recommended_blog_needs_no_note(self):
        self.add(blogs=("blogger_ko",))
        data = self.data("draft", "plan", "1")
        self.assertEqual((data["plan"]["blog"], data["notes"]), ("blogger_ko", []))

    def test_choose_blog_directly(self):
        candidate = cd.Candidate.new("주제", "키워드", ("naver_b", "naver_a"), now="2026-11-02T03:00:00Z")
        self.assertEqual(draft.choose_blog(candidate, None)[0], "naver_b")
        self.assertEqual(draft.choose_blog(candidate, "naver_a")[0], "naver_a")
        with self.assertRaises(Exception) as caught:
            draft.choose_blog(candidate, "tistory")
        self.assertEqual(caught.exception.code, "DRAFT_OPTION_INVALID")


class ProfileTest(Base):
    def test_the_blogs_profile_values_are_applied(self):
        self.add(blogs=("naver_a",))
        self.ctx.settings.save_naver_profile(NaverProfile("naver_a", "에이", "https://blog.naver.com/exampleaaa", audience="초보 집주인", default_tags=("생활",), max_tags=3, max_title_chars=20,
                                                          subheading_min=3, subheading_max=3, categories=(("생활", "생활정보"),)))
        data = self.data("draft", "plan", "1", "--blog", "naver_a")
        plan = data["plan"]
        self.assertTrue(data["profile_found"])
        self.assertEqual((plan["audience"], plan["category"], len(plan["tags"]), len(plan["subheadings"])), ("초보 집주인", "생활정보", 3, 3))
        self.assertTrue(all(len(title) <= 20 for title in plan["titles"]))
        self.assertEqual({item: layer for item, layer in plan["sources"].items() if item in ("audience", "subheadings", "title_limit", "tag_limit")}, {"audience": "profile", "subheadings": "profile", "title_limit": "profile", "tag_limit": "profile"})

    def test_a_missing_naver_profile_is_a_note_and_the_exit_code_is_still_zero(self):
        self.add(blogs=("naver_a",))
        out = self.ok("draft", "plan", "1", "--blog", "naver_a")
        self.assertIn("이 네이버 블로그의 프로필이 아직 없어 공통 기본값으로 만들었습니다", out)
        data = self.data("draft", "plan", "1", "--blog", "naver_a")
        self.assertFalse(data["profile_found"])

    def test_non_naver_blogs_have_no_profile_and_no_missing_profile_note(self):
        self.add(blogs=("github_pages",))
        out = self.ok("draft", "plan", "1")
        self.assertNotIn("프로필이 아직 없어", out)
        self.assertFalse(self.data("draft", "plan", "1")["profile_found"])

    def test_a_broken_settings_file_is_reported_and_not_hidden(self):
        self.add(blogs=("naver_a",))
        self.ctx.workspace.settings_path.write_text("{ 깨진 설정", encoding="utf-8")
        before = self.snapshot()
        err = self.fails("draft", "plan", "1", "--blog", "naver_a")
        self.assertIn("SETTINGS_INVALID", err)
        self.assertEqual(self.snapshot(), before)
        self.add(topic="깃허브 글", keyword="깃허브 키워드", blogs=("github_pages",))
        self.fails("draft", "plan", "2", "--blog", "naver_b")                         # 네이버 프로필을 읽으려는 순간에만 설정 파일을 본다


class BaseDateTest(Base):
    def test_the_base_date_is_the_korean_calendar_day(self):
        from datetime import datetime, timezone
        self.add(blogs=("github_pages",))
        for utc, expected in ((datetime(2026, 11, 2, 14, 59, 59, tzinfo=timezone.utc), "2026-11-02"), (datetime(2026, 11, 2, 15, 0, 0, tzinfo=timezone.utc), "2026-11-03"),
                              (datetime(2026, 11, 2, 20, 0, 0, tzinfo=timezone.utc), "2026-11-03"), (datetime(2026, 12, 31, 15, 30, 0, tzinfo=timezone.utc), "2027-01-01")):
            with self.subTest(utc=utc):
                self.ctx.clock.now = utc
                self.assertEqual(self.data("draft", "plan", "1")["plan"]["base_date"], expected)
                self.assertEqual(draft.today_kst(self.ctx), expected)


class ComparisonTest(Base):
    def test_a_candidate_for_both_naver_blogs_is_compared_with_the_other_blogs_plan(self):
        self.add(blogs=("naver_a", "naver_b"))
        ss.naver_profiles(self.ctx)
        data = self.data("draft", "plan", "1", "--blog", "naver_a")
        comparison = data["comparison"]
        self.assertEqual(comparison["blog"], "naver_b")
        self.assertEqual(comparison["level"], "ok")
        self.assertEqual(comparison["warnings"], [])
        self.assertLess(comparison["overall"], 0.4)
        out = self.ok("draft", "plan", "1", "--blog", "naver_a")
        self.assertIn("다른 네이버 블로그(네이버 B) 용 계획과 견줘 봤습니다.", out)
        self.assertIn("두 블로그 비교: 전체", out)
        other = self.data("draft", "plan", "1", "--blog", "naver_b")["comparison"]
        self.assertEqual((other["blog"], other["overall"]), ("naver_a", comparison["overall"]))

    def test_the_other_blogs_plan_is_made_with_the_other_blogs_profile(self):
        self.add(blogs=("naver_a", "naver_b"))
        self.ctx.settings.save_naver_profile(NaverProfile("naver_a", "에이", "https://blog.naver.com/exampleaaa", audience="에이 독자"))
        self.ctx.settings.save_naver_profile(NaverProfile("naver_b", "비", "https://blog.naver.com/examplebbb", audience="비 독자"))
        seen = []
        real = draft.dp.build_plan

        def spy(candidate, profile, options, **kwargs):
            seen.append((kwargs.get("blog"), None if profile is None else profile.key, None if profile is None else profile.audience))
            return real(candidate, profile, options, **kwargs)

        with mock.patch.object(draft.dp, "build_plan", side_effect=spy):
            self.ok("draft", "plan", "1", "--blog", "naver_a")
        self.assertEqual(seen, [("naver_a", "naver_a", "에이 독자"), ("naver_b", "naver_b", "비 독자")])

    def test_one_naver_blog_or_other_platforms_have_no_comparison(self):
        self.add(blogs=("naver_a",))
        self.assertIsNone(self.data("draft", "plan", "1")["comparison"])
        self.add(topic="깃허브 글", keyword="깃허브 키워드", blogs=("github_pages", "naver_a"))
        self.assertIsNone(self.data("draft", "plan", "2", "--blog", "github_pages")["comparison"])
        self.assertNotIn("견줘 봤습니다", self.ok("draft", "plan", "2", "--blog", "github_pages"))

    def test_the_same_options_are_used_for_the_other_blogs_plan(self):
        self.add(blogs=("naver_a", "naver_b"))
        data = self.data("draft", "plan", "1", "--blog", "naver_a", "--message", "아주 긴 똑같은 내용입니다 " * 8)
        self.assertEqual(data["comparison"]["level"], "ok")

    def test_the_result_object_carries_the_comparison(self):
        self.add(blogs=("naver_a", "naver_b"))
        result = draft.make_plan(self.ctx, "1", blog="naver_a")
        self.assertEqual(result.other_blog, "naver_b")
        self.assertEqual(result.comparison.level, "ok")
        self.assertEqual(result.plan.blog, "naver_a")
        self.assertEqual(result.row.ordinal, 1)


class OutputTest(Base):
    def setUp(self):
        super().setUp()
        self.add(blogs=("naver_a", "naver_b"), sub_keywords=("보일러 청소", "난방비"))
        ss.naver_profiles(self.ctx)

    def test_the_human_output_has_every_section_in_order_in_plain_korean(self):
        out = self.ok("draft", "plan", "1", "--blog", "naver_a")
        sections = ["작성 기반 — 후보 [1] 겨울 보일러 점검 순서 · 네이버 A 용 · 기준 날짜 2026-11-02", "글 유형: 정보형", "예상 검색 의도:", "대상 독자:", "핵심 키워드: 보일러 점검", "제목 후보:", "  1. ", "  3. ", "본문 작성 방향:",
                    "권장 목차와 소제목:", "포함할 핵심 내용:", "주의사항:", "추천 카테고리:", "추천 태그:", "참고할 수 있는 공개 자료:", "확인 권장(있어도 계획은 이대로 쓸 수 있습니다):", "다른 네이버 블로그(네이버 B)"]
        position = 0
        for section in sections:
            found = out.find(section, position)
            self.assertGreaterEqual(found, 0, section)
            position = found
        self.assertIn("아무것도 저장하지 않았습니다", out)
        self.assertNotRegex(out, STATUS_CODES)
        self.assertNotRegex(out, LONG_ID)
        self.assertNotIn("값이 온 곳", out)

    def test_every_title_outline_row_and_tag_is_listed_once(self):
        data = self.data("draft", "plan", "1", "--blog", "naver_a")
        plan, out = data["plan"], self.ok("draft", "plan", "1", "--blog", "naver_a")
        for title in plan["titles"]:
            self.assertIn(title, out)
        for number, (name, heading) in enumerate(zip(plan["outline"], plan["subheadings"]), 1):
            self.assertIn(f"  {number}. {name} — {heading}", out)
        self.assertIn(" ".join("#" + tag for tag in plan["tags"]), out)
        for point in plan["key_points"]:
            self.assertIn(f"  - {point}", out)

    def test_verbose_adds_where_each_value_came_from(self):
        out = self.ok("draft", "plan", "1", "--blog", "naver_a", "--audience", "직장인", "--verbose")
        self.assertIn("값이 온 곳(적용 순서: 사용자 입력 → 블로그 프로필 → 글 유형 틀 → 후보(키워드 분석) → 공통 기본값", out)
        self.assertIn("  - 대상 독자: 사용자 입력", out)
        self.assertIn("  - 문체: 공통 기본값", out)
        self.assertIn("  - 소제목 수: 공통 기본값", out)                                       # 프로필이 기본값뿐이면 정하지 않은 것으로 본다(글 길이와 같은 규칙)
        self.assertIn("  - 글 길이: 블로그 프로필", out)                                         # 이 시험의 프로필은 글 길이만 정했다
        self.assertNotIn("값이 온 곳", self.ok("draft", "plan", "1", "--blog", "naver_a"))

    def test_the_json_shape_and_the_sources(self):
        payload = json.loads(self.ok("--json", "draft", "plan", "1", "--blog", "naver_a"))
        self.assertEqual((payload["ok"], payload["command"]), (True, "draft plan"))
        data = payload["data"]
        self.assertEqual(set(data), {"read_only", "candidate", "plan", "options", "notes", "profile_found", "comparison"})
        self.assertTrue(data["read_only"])
        self.assertEqual(data["candidate"]["ordinal"], 1)
        self.assertEqual(data["options"], DraftOptions().to_dict())
        self.assertEqual(data["plan"]["sources"]["audience"], "default")
        self.assertTrue(data["plan"]["complete"])
        self.assertEqual(len(data["plan"]["titles"]), 3)

    def test_every_option_reaches_the_plan(self):
        data = self.data("draft", "plan", "1", "--blog", "naver_a", "--message", "전하고 싶은 말", "--experience", EXPERIENCE, "--opinion", "의견입니다", "--must-include", "첫 문장입니다", "--must-include", "둘째 문장입니다",
                         "--exclude", "광고,가격", "--exclude", "협찬", "--audience", "사회 초년생", "--length", "2,500~3,000", "--title-direction", "질문형", "--url", "https://example.com/a", "--url", "https://example.com/b",
                         "--price-date", "정가 12,000원", "--price-date", "2026-11-01 기준", "--conclusion", "비교 뒤에 고르세요")
        plan, options = data["plan"], data["options"]
        self.assertEqual(options, {"schema": 1, "message": "전하고 싶은 말", "experience": EXPERIENCE, "opinion": "의견입니다", "must_include": ["첫 문장입니다", "둘째 문장입니다"], "exclude": ["광고", "가격", "협찬"],
                                   "audience": "사회 초년생", "length": "2500-3000", "title_direction": "질문형", "urls": ["https://example.com/a", "https://example.com/b"], "price_date": ["정가 12,000원", "2026-11-01 기준"],
                                   "conclusion": "비교 뒤에 고르세요"})
        self.assertEqual((plan["audience"], plan["length"], plan["references"]), ("사회 초년생", {"min": 2500, "max": 3000}, ["https://example.com/a", "https://example.com/b"]))
        self.assertIn("경험 이야기", " ".join(plan["outline"]))
        self.assertIn(f"실제 경험(입력): {EXPERIENCE}", plan["key_points"])
        self.assertEqual([plan["sources"][item] for item in ("audience", "length", "title_direction", "conclusion")], ["user"] * 4)

    def test_references_and_the_users_lines_are_printed_in_the_human_output_too(self):
        out = self.ok("draft", "plan", "1", "--blog", "naver_a", "--url", "https://example.com/a", "--url", "https://example.com/b", "--price-date", "정가 12,000원", "--conclusion", "비교 뒤에 고르세요",
                      "--must-include", "꼭 넣을 문장입니다")
        for needle in ("참고할 수 있는 공개 자료(입력한 주소만 — 앱은 열어 보거나 가져오지 않았습니다):", "  - https://example.com/a", "  - https://example.com/b", "  - 가격·날짜(입력): 정가 12,000원",
                       "  - 마무리에 넣을 결론(입력): 비교 뒤에 고르세요", "  - 반드시 넣을 문장(입력): 꼭 넣을 문장입니다", "  - 결론(입력): 비교 뒤에 고르세요"):
            self.assertIn(needle, out)
        self.assertIn("참고할 수 있는 공개 자료: 입력한 주소가 없습니다", self.ok("draft", "plan", "1", "--blog", "naver_a"))

    def test_a_replacement_is_announced_with_the_right_particle(self):
        self.add(topic="무선 이어폰 체험단 후기", keyword="이어폰 체험 후기", blogs=("naver_a",))
        out = self.ok("draft", "plan", "2", "--blog", "naver_a")
        self.assertIn("※ 후보의 ‘제품 체험 후기’ 형식은 ‘공개된 제품 정보와 구매 전 확인사항’으로 바꿔 구성했습니다(경험을 지어내지 않습니다).", out)
        self.assertNotIn("확인사항’ 로", out)
        self.add(topic="서울 맛집 방문 후기", keyword="맛집 방문 후기", blogs=("naver_a",))
        self.assertIn("형식은 ‘위치·이용 정보와 방문 전 확인사항’으로 바꿔 구성했습니다", self.ok("draft", "plan", "3", "--blog", "naver_a"))

    def test_the_type_option_overrides_the_candidates_type(self):
        data = self.data("draft", "plan", "1", "--blog", "naver_a", "--type", "비교형")
        self.assertEqual((data["plan"]["post_type"], data["plan"]["sources"]["post_type"], data["plan"]["outline"][0]), ("비교형", "user", "비교 목적"))

    def test_every_option_is_optional_and_empty_values_are_fine(self):
        out = self.ok("draft", "plan", "1", "--blog", "naver_a", "--experience", "", "--message", "", "--length", "", "--url", "", "--exclude", "")
        self.assertIn("확인 권장", out)
        self.assertEqual(self.data("draft", "plan", "1", "--blog", "naver_a", "--experience", "")["options"], DraftOptions().to_dict())

    def test_a_secret_shaped_string_in_an_option_is_refused_and_never_printed(self):
        err = self.fails("draft", "plan", "1", "--blog", "naver_a", "--message", f"비밀 {ss.KEY} 입니다")
        self.assertNotIn(ss.KEY, err)
        self.assertIn("DRAFT_OPTION_INVALID", err)
        self.assertIn("직접 전달하고 싶은 내용", err)
        self.assertIn("비밀번호·키·토큰처럼 보이는 글", err)
        payload = self.error_json("draft", "plan", "1", "--blog", "naver_a", "--opinion", f"의견 {ss.KEY}")
        self.assertNotIn(ss.KEY, json.dumps(payload, ensure_ascii=False))
        self.assertEqual(payload["error"]["code"], "DRAFT_OPTION_INVALID")
        err = self.fails("draft", "plan", "1", "--blog", "naver_a", "--url", f"https://example.com/?x={ss.KEY}&token=abc")
        self.assertNotIn(ss.KEY, err)
        err = self.fails("draft", "plan", "1", "--blog", "naver_a", "--url", f"https://example.com/{ss.KEY}")
        self.assertNotIn(ss.KEY, err)
        self.assertIn("참고 URL", err)


SECRET_SHAPES = (                                             # 키 모양의 가짜 값 — 저장소에는 키 모양 글이 통째로 있으면 안 되므로 조각을 이어서 만든다
    "AI" + "zaSyA1234567890abcdefghijklmnopqrstuvw",
    "gh" + "p_1234567890abcdefghijklmnopqrstuvwxyz",
    "s" + "k-abcdefghijklmnopqrstuvwxyz1234567890",
    "AK" + "IAIOSFODNN7EXAMPLE",
)


class SecretShapedOptionsTest(Base):
    """모든 옵션에 비밀 모양의 글을 넣어도(맞는 자리든 틀린 자리든) 화면·`--json`·`--verbose`·오류 어디에도 그 글자의 앞이나 뒤 12자가 나오지 않는다 — 마스크는 전체 모양만 알아보므로 잘린 조각은 못 막는다."""

    def setUp(self):
        super().setUp()
        self.add(blogs=("naver_a",))

    def assert_hidden(self, secret, *argv):
        for mode in (("--verbose",), ("--json", "--verbose")):
            code, out, err = self.run_cli("draft", "plan", "1", "--blog", "naver_a", *mode, *argv)
            bag = out + err
            self.assertIn(code, (0, 1, 2), (argv, bag[:200]))
            self.assertNotIn("Traceback", bag)
            self.assertNotIn(secret[:12], bag, (mode, argv))
            self.assertNotIn(secret[-12:], bag, (mode, argv))

    def test_every_option_hides_a_secret_shaped_value(self):
        for secret in SECRET_SHAPES:
            for flag in ("--message", "--experience", "--opinion", "--must-include", "--exclude", "--audience", "--length", "--title-direction", "--url", "--price-date", "--conclusion", "--type"):
                for value in (secret, "앞의 글 " + secret + " 뒤의 글"):
                    with self.subTest(flag=flag, secret=secret[:6], wrapped=value != secret):
                        self.assert_hidden(secret, flag, value)

    def test_a_key_stuck_to_hangul_is_refused_in_every_option_and_never_printed(self):
        for secret in SECRET_SHAPES:
            for value in (secret + "를 쓰세요", "키" + secret, "키는" + secret + "입니다", "(" + secret + ")", '"' + secret + '"', secret + ".", secret + "," + "끝"):
                for flag in ("--message", "--experience", "--opinion", "--must-include", "--exclude", "--audience", "--title-direction", "--price-date", "--conclusion"):
                    with self.subTest(secret=secret[:6], flag=flag, value=value[:8]):
                        code, out, err = self.run_cli("draft", "plan", "1", "--blog", "naver_a", "--json", "--verbose", flag, value)
                        self.assertEqual(code, 1)
                        self.assertIn("DRAFT_OPTION_INVALID", out + err)
                        self.assertNotIn(secret[:12], out + err)
                        self.assertNotIn(secret[-12:], out + err)

    def test_wrong_shaped_addresses_hide_every_part(self):
        for secret in SECRET_SHAPES:
            for value in (secret + ":path", "ftp://" + secret, "https://example.com/?token=" + secret, "https://example.com/#access_token=" + secret, "https://user:" + secret + "@example.com/",
                          "https://" + secret + "/x", "https://example.com:" + secret + "/"):
                with self.subTest(secret=secret[:6], value=value[:24]):
                    self.assert_hidden(secret, "--url", value)

    def test_a_secret_as_the_candidate_number_or_the_blog_is_hidden_too(self):
        for secret in SECRET_SHAPES:
            for argv in (("draft", "plan", secret), ("draft", "plan", secret[:8]), ("draft", "plan", "1", "--blog", secret)):
                with self.subTest(secret=secret[:6], argv=argv[2:4]):
                    for mode in ((), ("--json",)):
                        code, out, err = self.run_cli(*mode, *argv)
                        self.assertIn(code, (1, 2))
                        self.assertNotIn(secret[:12], out + err)
                        self.assertNotIn(secret[-12:], out + err)
                        self.assertNotIn("Traceback", out + err)


class InvalidInputTest(Base):
    def setUp(self):
        super().setUp()
        self.add(blogs=("naver_a",))

    def test_wrong_values_are_a_handled_error_with_the_field_and_the_reason(self):
        cases = (
            (("--url", "http://example.com/a"), "참고 URL", "https://"), (("--url", "javascript:alert(1)"), "참고 URL", "https://"), (("--url", "https://user:pw@example.com/"), "참고 URL", "로그인 정보"),
            (("--length", "2000"), "원하는 글 길이", "모양"), (("--length", "300-250"), "원하는 글 길이", "상한"), (("--length", "50+"), "원하는 글 길이", "200"), (("--type", "후기형"), "글 유형", "정보형"),
            (("--message", "<script>alert(1)</script>"), "직접 전달하고 싶은 내용", "HTML"), (("--opinion", "상위노출 보장"), "개인 의견", "결과를 약속하는 표현"),
            (("--conclusion", "가" * 301), "최종 결론", "300자 이하"), (("--audience", "가" * 101), "특정 독자층", "100자 이하"), (("--title-direction", "{% x %}"), "원하는 제목 방향", "템플릿"),
            (("--must-include", "가" * 201), "반드시 포함할 문장", "200자 이하"), (("--price-date", "가" * 101), "실제 가격이나 날짜", "100자 이하"),
        )
        for extra, field, reason in cases:
            with self.subTest(extra=extra[:2]):
                err = self.fails("draft", "plan", "1", "--blog", "naver_a", *extra)
                self.assertIn("DRAFT_OPTION_INVALID", err)
                self.assertIn(field, err)
                self.assertIn(reason, err)
                self.assertIn("하실 일:", err)
                self.assertNotIn("Traceback", err)
        self.assertFalse(self.root.joinpath("settings.json").exists())

    def test_the_json_error_shape(self):
        payload = self.error_json("draft", "plan", "1", "--blog", "naver_a", "--url", "http://example.com")
        self.assertEqual((payload["command"], payload["error"]["code"]), ("draft plan", "DRAFT_OPTION_INVALID"))
        self.assertIn("참고 URL", payload["error"]["message"])
        self.assertEqual(payload["error"]["retry"], "고친 뒤")

    def test_too_many_items_are_refused(self):
        args = [item for index in range(11) for item in ("--must-include", f"문장 {index}")]
        self.assertIn("10개까지", self.fails("draft", "plan", "1", *args))
        args = [item for index in range(11) for item in ("--url", f"https://example.com/{index}")]
        self.assertIn("10개까지", self.fails("draft", "plan", "1", *args))

    def test_nothing_was_saved_after_a_refusal(self):
        before = self.snapshot()
        self.fails("draft", "plan", "1", "--url", "ftp://example.com")
        self.assertEqual(self.snapshot(), before)


class UsageTest(Base):
    def group(self):
        return cli.build_parser()._subparsers._group_actions[0].choices["draft"]

    def test_the_draft_command_has_exactly_the_plan_subcommand(self):
        self.assertEqual(set(self.group()._subparsers._group_actions[0].choices), {"plan"})
        self.assertIn("draft", cli.build_parser()._subparsers._group_actions[0].choices)

    def test_every_help_screen_is_korean(self):
        for argv in (("draft", "--help"), ("draft", "plan", "--help"), ("draft", "-h"), ("draft", "plan", "-h")):
            with self.subTest(argv=argv):
                code, out, err = self.run_cli(*argv)
                self.assertEqual((code, err), (0, ""), err)
                for needle in ("사용법:", "옵션", "이 도움말을 보여 주고 끝냅니다"):
                    self.assertIn(needle, out)
                for word in ENGLISH:
                    self.assertNotIn(word, out)
        code, out, _err = self.run_cli("draft", "plan", "--help")
        for needle in ("--experience", "--must-include", "--exclude", "--length", "--title-direction", "--url", "--price-date", "--conclusion", "--blog", "--type", "--message", "--opinion", "--audience", "읽기만"):
            self.assertIn(needle, out)
        self.assertIn("모든 입력은 선택입니다", out)

    def test_usage_errors_are_korean_and_exit_two(self):
        cases = ((("draft",), "빠진 항목이 있습니다: 하위명령"), (("draft", "nosuch"), "에 쓸 수 없는 값"), (("draft", "plan"), "빠진 항목이 있습니다: 번호"), (("draft", "plan", "1", "--nope"), "알 수 없는 항목입니다"),
                 (("draft", "plan", "1", "--blog", "네이버"), "알 수 없는 블로그"), (("draft", "plan", "1", "--blog", "naver_a,naver_b"), "하나만"), (("draft", "plan", "1", "--length"), "값이 필요합니다"),
                 (("draft", "plan", "1", "--blog", "tistory"), "알 수 없는 블로그"))
        for argv, needle in cases:
            with self.subTest(argv=argv):
                err = self.fails(*argv, code=2)
                self.assertIn("사용법 오류", err)
                self.assertIn(needle, err)
                for word in ("the following", "unrecognized", "invalid choice"):
                    self.assertNotIn(word, err)

    def test_option_names_cannot_be_shortened(self):
        self.add(blogs=("naver_a",))
        for argv in (("draft", "plan", "1", "--exp", "경험"), ("draft", "plan", "1", "--must", "문장"), ("draft", "plan", "1", "--bl", "naver_a"), ("draft", "plan", "1", "--len", "2500+"), ("draft", "plan", "1", "--js")):
            with self.subTest(argv=argv):
                code, out, err = self.run_cli(*argv)
                self.assertEqual((code, out), (2, ""), (argv, err))
                self.assertIn("사용법 오류", err)

    def test_the_options_in_the_common_set_work_after_the_subcommand(self):
        self.add(blogs=("naver_a",))
        self.assertTrue(self.data("draft", "plan", "1")["plan"])
        out = self.ok("draft", "plan", "1", "--verbose")
        self.assertIn("값이 온 곳", out)


if __name__ == "__main__":
    unittest.main()
