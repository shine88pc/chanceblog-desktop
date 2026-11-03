"""명령줄 `candidates` 시험(같은 프로세스에서 돌린다 — 진짜 프로세스 시험은 test_service_candidates_process.py). 출력의 모양·종료 코드·`--json`·사용법 오류·도움말·비밀 가리기.

지키는 것:
  1) 사람이 읽는 출력에는 영문 상태 코드(NEW·SELECTED …)도 후보의 긴 번호도 나오지 않는다 — 번호 전체는 `--json`·`--verbose` 에서만.
  2) 종료 코드: 0 정상 · 1 처리된 오류(오류 코드와 하실 일, 스택 추적 없음) · 2 사용법 오류. CSV 에서 거절한 줄이 있으면 1(나머지는 이미 저장됨).
  3) 옵션 줄임말(`--stat`·`--y`)은 받지 않고 아무것도 바꾸지 않는다. 도움말·사용법 오류는 한국어이고 하위 명령도 같다.
  4) 지우기는 `--yes` 가 없으면 `CONFIRMATION_REQUIRED` 로 멈춘다(`CANDIDATE_CONFIRM_REQUIRED` 가 아니다). `list`·`show` 는 보관함을 만들지 않는다.
  5) 후보의 글에 키 모양 문자열이 있어도 화면(글·JSON·오류)에는 가려져 나간다.
"""
import json
import re
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import service_support as ss  # noqa: E402

from chanceblog_desktop.content import candidates as cd  # noqa: E402
from chanceblog_desktop.content.profiles import NaverProfile  # noqa: E402
from chanceblog_desktop.content.store import Store  # noqa: E402
from chanceblog_desktop.errors import CATALOG  # noqa: E402
from chanceblog_desktop.service import candidates as svc  # noqa: E402
from chanceblog_desktop.service import cli, projects  # noqa: E402

ENGLISH = ("usage:", "positional arguments", "options:", "optional arguments", "show this help message and exit")
STATUS_CODES = re.compile(r"\b(?:NEW|REVIEW|SELECTED|HOLD|REJECTED)\b")
LONG_ID = re.compile(r"\b[0-9a-f]{32}\b")
SUBCOMMANDS = {"list", "show", "add", "import-csv", "select", "hold", "reject", "review", "restore", "delete", "link", "unlink"}


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

    def add(self, topic, keyword=None, blog="naver_a", *extra):
        self.ctx.clock.advance(seconds=1)
        return self.ok("candidates", "add", "--topic", topic, "--keyword", keyword or topic + " 키워드", "--blog", blog, *extra)

    def stored(self):
        with self.ctx.store() as store:
            return svc.numbered(store.list_candidates())

    def number(self, ordinal):
        """그 순번 후보의 번호 앞 8자 — 화면에 보이는 '번호' 이고, 지울 때는 순번이 아니라 이것으로 정한다."""
        return self.stored()[ordinal - 1].candidate.candidate_id[:8]


class HelpAndUsageTest(Base):
    def group(self):
        return cli.build_parser()._subparsers._group_actions[0].choices["candidates"]

    def test_the_candidates_command_has_exactly_the_documented_subcommands(self):
        self.assertEqual(set(self.group()._subparsers._group_actions[0].choices), SUBCOMMANDS)

    def test_every_help_screen_is_korean_for_the_group_and_each_subcommand(self):
        for name in [None, *sorted(SUBCOMMANDS)]:
            with self.subTest(command=name or "(하위 명령 목록)"):
                code, out, err = self.run_cli("candidates", *([name] if name else []), "--help")
                self.assertEqual((code, err), (0, ""), err)
                for needle in ("사용법:", "옵션", "이 도움말을 보여 주고 끝냅니다"):
                    self.assertIn(needle, out)
                for word in ENGLISH:
                    self.assertNotIn(word, out)
        code, out, err = self.run_cli("candidates", "-h")
        self.assertEqual((code, err), (0, ""))
        self.assertIn("select", out)

    def test_the_top_level_help_lists_the_command(self):
        code, out, err = self.run_cli("--help")
        self.assertEqual((code, err), (0, ""))
        self.assertIn("candidates", out)

    def test_a_missing_or_unknown_subcommand_is_a_korean_usage_error(self):
        for argv, needle in ((("candidates",), "빠진 항목이 있습니다: 하위명령"), (("candidates", "nosuch"), "에 쓸 수 없는 값"), (("candidates", "list", "extra"), "알 수 없는 항목입니다")):
            with self.subTest(argv=argv):
                err = self.fails(*argv, code=2)
                self.assertIn("사용법 오류", err)
                self.assertIn(needle, err)
                for word in ("the following", "unrecognized", "invalid choice"):
                    self.assertNotIn(word, err)

    def test_a_usage_error_names_the_missing_options_and_points_at_the_help(self):
        err = self.fails("candidates", "add", "--topic", "x", code=2)
        self.assertIn("빠진 항목이 있습니다: --keyword, --blog", err)
        self.assertIn("도움말: python -m chanceblog_desktop --help", err)

    def test_option_names_cannot_be_shortened_and_nothing_happens(self):
        self.add("지울 후보")
        for argv in (("candidates", "list", "--stat", "선택됨"), ("candidates", "list", "--jso"), ("candidates", "delete", "1", "--y"), ("candidates", "delete", "1", "--ye"),
                     ("candidates", "select", "1", "--bl", "naver_a"), ("candidates", "add", "--top", "x", "--keyword", "y", "--blog", "naver_a"),
                     ("candidates", "--js", "list"), ("candidates", "import-csv", "x.csv", "--data", "2026-11-01"), ("--dat", "x", "candidates", "list")):
            with self.subTest(argv=argv):
                code, out, err = self.run_cli(*argv)
                self.assertEqual((code, out), (2, ""), (argv, err))
                self.assertIn("사용법 오류", err)
        self.assertEqual(len(self.stored()), 1, "아무것도 지워지거나 더해지지 않았다")

    def test_an_unknown_blog_lists_the_choices_with_their_names_and_the_quoting_hint(self):
        for argv in (("candidates", "list", "--blog", "네이버"), ("candidates", "select", "1", "--blog", "네이버"), ("candidates", "add", "--topic", "x", "--keyword", "y", "--blog", "네이버"),
                     ("candidates", "import-csv", "x.csv", "--blog", "티스토리")):
            with self.subTest(argv=argv):
                err = self.fails(*argv, code=2)
                for needle in ("알 수 없는 블로그", "naver_a(네이버 A)", "github_pages(GitHub Pages)", "blogger_ko(Blogger 한글)", "따옴표로 묶습니다", '--blog "네이버 A"'):
                    self.assertIn(needle, err)

    def test_the_import_help_names_the_required_and_optional_columns(self):
        code, out, err = self.run_cli("candidates", "import-csv", "--help")
        self.assertEqual((code, err), (0, ""))
        for needle in ("`주제`·`핵심 키워드`·`대상 블로그`", "월간 검색 수요", "데이터 조회일", "--data-date", "종료 코드 1"):
            self.assertIn(needle, out)

    def test_values_that_are_not_allowed_are_usage_errors_in_korean(self):
        self.add("가")
        for argv, needle in ((("candidates", "list", "--status", "폭등"), "새 후보, 검토 중, 선택됨, 보류, 제외"), (("candidates", "list", "--blog", "tistory"), "알 수 없는 블로그"),
                             (("candidates", "list", "--blog", "naver_a,naver_b"), "하나만"), (("candidates", "select", "1", "--blog", "tistory"), "알 수 없는 블로그"),
                             (("candidates", "select", "1", "--blog", "naver_a,naver_b"), "하나만"), (("candidates", "select", "1"), "--blog"),
                             (("candidates", "add", "--topic", "x", "--keyword", "y", "--blog", "tistory"), "알 수 없는 블로그"), (("candidates", "add", "--topic", "x", "--keyword", "y"), "--blog"),
                             (("candidates", "add", "--topic", "x", "--keyword", "y", "--blog", "naver_a", "--data-date", "2026/11/01"), "2026-11-02 같은 모양"),
                             (("candidates", "add", "--topic", "x", "--keyword", "y", "--blog", "naver_a", "--trend", "폭등"), "상승"),
                             (("candidates", "add", "--topic", "x", "--keyword", "y", "--blog", "naver_a", "--search-demand", "많이"), "숫자"),
                             (("candidates", "add", "--topic", "x", "--keyword", "y", "--blog", "naver_a", "--mobile-share", "101"), "0~100 사이의 숫자"),
                             (("candidates", "add", "--topic", "x", "--keyword", "y", "--blog", "naver_a", "--priority", "abc"), "0~100 사이의 숫자"),
                             (("candidates", "add", "--topic", "x", "--keyword", "y", "--blog", "naver_a", "--seasonality", "봄"), "달(1~12)"),
                             (("candidates", "add", "--topic", "x", "--keyword", "y", "--blog", "naver_a", "--duplicate", "글쎄"), "예·아니오"),
                             (("candidates", "import-csv", "x.csv", "--data-date", "내일"), "2026-11-02 같은 모양"), (("candidates", "import-csv"), "파일"), (("candidates", "show"), "번호"),
                             (("candidates", "link", "1"), "글번호")):
            with self.subTest(argv=argv):
                err = self.fails(*argv, code=2)
                self.assertIn("사용법 오류", err)
                self.assertIn(needle, err)
        self.assertEqual([row.candidate.status for row in self.stored()], [cd.NEW])


class ListAndShowTest(Base):
    def test_listing_a_missing_store_says_so_and_creates_nothing(self):
        out = self.ok("candidates", "list")
        self.assertIn("아직 후보가 없습니다(쓰는 명령을 처음 실행하면 보관함이 올라갑니다)", out)
        self.assertIn("candidates add", out)
        self.assertFalse(self.root.exists())
        data = self.data("candidates", "list")
        self.assertEqual((data["candidates"], data["total"], data["store"]), ([], 0, "missing"))
        self.fails("candidates", "show", "1")
        self.assertFalse(self.root.exists())

    def test_an_empty_current_store_gives_the_plain_empty_message(self):
        self.add("가")
        svc.delete_candidate(self.ctx, self.number(1), confirmed=True)
        out = self.ok("candidates", "list")
        self.assertIn("아직 후보가 없습니다. ", out)
        self.assertNotIn("보관함이 올라갑니다", out)

    def test_the_list_shows_ordinals_korean_names_and_no_internal_codes_or_numbers(self):
        self.add("겨울 보일러 점검 순서", "보일러 점검", "naver_a,pages")
        self.add("전기장판 쓰는 법", "전기장판", "naver_b")
        self.ok("candidates", "select", "1", "--blog", "pages")
        self.ok("candidates", "reject", "2")
        out = self.ok("candidates", "list")
        lines = out.splitlines()
        self.assertEqual(lines[0], "주제 후보 2개")
        self.assertEqual(lines[1], f"  [1] 선택됨(GitHub Pages) — 겨울 보일러 점검 순서 · 핵심 키워드: 보일러 점검 · 대상: 네이버 A, GitHub Pages · 번호 {self.number(1)}")
        self.assertEqual(lines[2], f"  [2] 제외 — 전기장판 쓰는 법 · 핵심 키워드: 전기장판 · 대상: 네이버 B · 번호 {self.number(2)}")
        self.assertIn("순번은 전체 목록 기준이고, 후보를 지우면 뒤의 순번이 하나씩 당겨집니다", lines[3])
        self.assertEqual(lines[4], "지울 때는 순번이 아니라 번호 앞 8자를 씁니다: `python -m chanceblog_desktop candidates delete 번호 --yes`.")
        self.assertEqual(len(lines), 5)
        self.assertIsNone(STATUS_CODES.search(out), "영문 상태 코드는 사람이 읽는 출력에 나오지 않는다")
        self.assertIsNone(LONG_ID.search(out), "후보의 긴 번호도 나오지 않는다")

    def test_the_whole_number_appears_only_with_json_or_verbose(self):
        self.add("가")
        candidate_id = self.stored()[0].candidate.candidate_id
        plain, verbose = self.ok("candidates", "list"), self.ok("--verbose", "candidates", "list")
        self.assertNotIn(candidate_id, plain)
        self.assertIn(f"번호 {candidate_id[:8]}", plain, "번호 앞 8자는 늘 보인다")
        self.assertIn(f"번호 {candidate_id}", verbose)
        self.assertIn(candidate_id, self.ok("candidates", "list", "--json"))
        self.assertNotIn(candidate_id, self.ok("candidates", "show", "1"))
        self.assertIn(f"번호: {candidate_id}", self.ok("candidates", "show", "1", "--verbose"))
        data = self.data("candidates", "list")
        self.assertEqual((data["candidates"][0]["candidate_id"], data["candidates"][0]["status"], data["candidates"][0]["status_name"], data["candidates"][0]["ordinal"]), (candidate_id, "NEW", "새 후보", 1))
        self.assertEqual((data["total"], data["shown"], data["store"]), (1, 1, "ready"))

    def test_the_filters_take_korean_names_short_words_codes_and_blog_aliases(self):
        self.add("가", "키워드 가", "naver_a")
        self.add("나", "키워드 나", "naver_b")
        self.add("다", "키워드 다", "pages")
        self.ok("candidates", "select", "2", "--blog", "naver_b")
        self.ok("candidates", "hold", "3")

        def shown(*argv):
            return [item["ordinal"] for item in self.data("candidates", "list", *argv)["candidates"]]

        for spelling in ("선택됨", "선택", "SELECTED", "selected", " 선택 됨 "):
            self.assertEqual(shown("--status", spelling), [2], spelling)
        self.assertEqual(shown("--status", "새 후보"), [1])
        self.assertEqual(shown("--status", "새후보"), [1])
        self.assertEqual(shown("--status", "보류"), [3])
        self.assertEqual(shown("--status", "hold"), [3])
        self.assertEqual(shown("--status", "제외"), [])
        self.assertEqual(shown("--blog", "pages"), [3])
        self.assertEqual(shown("--blog", "GitHub Pages"), [3])
        self.assertEqual(shown("--blog", "네이버 B"), [2])
        self.assertEqual(shown("--blog", "naver_a", "--status", "새 후보"), [1])
        out = self.ok("candidates", "list", "--status", "제외")
        self.assertEqual(out.strip(), "조건에 맞는 후보가 없습니다(전체 3개 — 상태: 제외).")
        head = self.ok("candidates", "list", "--blog", "pages", "--status", "보류").splitlines()[0]
        self.assertEqual(head, "주제 후보 1개(전체 3개 중 — 상태: 보류 · 블로그: GitHub Pages)")

    def test_show_lists_every_field_with_its_screen_name_and_says_no_data_when_there_is_none(self):
        self.add("겨울 보일러 점검 순서", "보일러 점검", "naver_a,pages", "--sub-keywords", "보일러 에러,난방비 절약", "--post-type", "문제 해결형", "--reason", "겨울 전에 찾는 사람이 늘어요",
                 "--data-date", "2026-11-01", "--search-demand", "12000", "--related-results", "34500", "--trend", "상승", "--mobile-share", "72.5", "--seasonality", "11,12,1", "--duplicate", "아니오",
                 "--profile-fit", "81", "--priority", "76.5", "--opportunity", "64")
        self.add("자료 없는 후보")
        out = self.ok("candidates", "show", "1")
        for needle in ("후보 [1]: 겨울 보일러 점검 순서", "상태: 새 후보", "핵심 키워드: 보일러 점검", "보조 키워드: 보일러 에러, 난방비 절약", "추천 대상 블로그: 네이버 A, GitHub Pages", "추천 글 유형: 문제 해결형",
                       "추천 이유: 겨울 전에 찾는 사람이 늘어요", "지표(데이터 조회일 2026-11-01):", "월간 검색 수요: 12,000회", "관련 블로그 검색 결과 수: 34,500건", "최근 관심도 변화: 상승",
                       "모바일 비중: 72.5%", "계절성: 1월·11월·12월", "기존 글 중복 여부: 아니오", "블로그 프로필 적합도: 81", "콘텐츠 작성 우선도: 76.5", "키워드 기회도: 64", "만든 때:"):
            self.assertIn(needle, out)
        self.assertIn("지표: 데이터 없음", self.ok("candidates", "show", "2"))
        self.assertIn("candidates select 1 --blog", out, "다음에 할 일을 알려 준다")

    def test_show_names_the_blogs_it_was_chosen_for_and_the_linked_post(self):
        project_id = projects.new_project(self.ctx, "연결한 글 제목", ss.ko_text()).project_id
        self.add("가")
        self.ok("candidates", "select", "1", "--blog", "naver_a")
        self.ok("candidates", "link", "1", project_id)
        out = self.ok("candidates", "show", "1")
        self.assertIn("상태: 선택됨(네이버 A)", out)
        self.assertIn("네이버 A 용으로 고른 때:", out)
        self.assertIn(f"연결한 글: 연결한 글 제목(글번호 {project_id[:8]}) — 아직 어느 곳에도 내보내지 않았습니다", out)
        self.assertNotIn("link 1 글번호", out, "이미 이어졌으면 연결 안내는 없다")
        self.assertIn("글 연결됨", self.ok("candidates", "list"))
        data = self.data("candidates", "show", "1")["candidate"]
        self.assertEqual((data["project_id"], data["project"]["title"], data["selections"]), (project_id, "연결한 글 제목", {"naver_a": self.ctx.stamp()}))

    def test_a_number_that_matches_nothing_or_too_many_is_a_handled_error_with_the_list_of_matches(self):
        self.add("가")
        err = self.fails("candidates", "show", "9")
        self.assertIn("코드: CANDIDATE_NOT_FOUND", err)
        self.assertIn("순번 9", err)
        payload = self.error_json("candidates", "show", "zzzz")
        self.assertEqual((payload["command"], payload["error"]["code"]), ("candidates show", "CANDIDATE_NOT_FOUND"))
        self.ctx.clock.advance(seconds=1)                      # 아래 두 후보가 '가' 보다 늦게 만든 것이 되도록(같은 초면 무작위 번호가 순서를 정한다)
        with self.ctx.store() as store:
            for candidate_id in ("abcd0001", "abcd0002"):
                store.save_candidate(cd.Candidate.new(f"겹친 {candidate_id}", f"키워드 {candidate_id}", ("naver_a",), candidate_id=candidate_id, now=self.ctx.stamp()))
        err = self.fails("candidates", "show", "abcd")
        self.assertIn("후보 번호가 여러 개와 겹칩니다", err)
        self.assertIn("코드: CANDIDATE_AMBIGUOUS", err)
        self.assertIn("순번 2 겹친 abcd0001", err)
        self.assertIn("순번 3 겹친 abcd0002", err)
        self.assertEqual(self.error_json("candidates", "show", "abcd")["error"]["code"], "CANDIDATE_AMBIGUOUS")
        self.assertIn("겹친 abcd0002", self.ok("candidates", "show", "abcd0002"))


class WriteCommandsTest(Base):
    def test_add_prints_the_new_line_and_json_says_whether_it_was_added(self):
        out = self.add("겨울 보일러 점검 순서", "보일러 점검", "naver_a,pages")
        self.assertEqual(out.splitlines()[0], "후보를 추가했습니다.")
        self.assertEqual(out.splitlines()[1], f"  [1] 새 후보 — 겨울 보일러 점검 순서 · 핵심 키워드: 보일러 점검 · 대상: 네이버 A, GitHub Pages · 번호 {self.number(1)}")
        again = self.ok("candidates", "add", "--topic", "겨울 보일러 점검 순서", "--keyword", "보일러점검", "--blog", "naver_a")
        self.assertIn("같은 핵심 키워드·주제·블로그의 후보가 이미 있어 추가하지 않았습니다(순번 1).", again)
        data = self.data("candidates", "add", "--topic", "겨울 보일러 점검 순서", "--keyword", "보일러 점검", "--blog", "pages")
        self.assertEqual((data["added"], data["duplicate_of"]["ordinal"]), (False, 1))
        self.assertEqual(len(self.stored()), 1)

    def test_the_blog_option_can_be_repeated_joined_with_commas_and_written_as_a_name(self):
        for spelling in (("--blog", "naver_a", "--blog", "naver_b"), ("--blog", "naver_a,naver_b"), ("--blog", "네이버 A, 네이버 B"), ("--blog", "naver_b,naver_a,naver_b"),
                         ("--blog", "naver_a", "--blog", "naver_b", "--blog", "naver_a"), ("--blog", "naver_a,naver_b", "--blog", "naver_b")):
            with self.subTest(spelling=spelling):
                self.setUp()
                self.ok("candidates", "add", "--topic", "주제", "--keyword", "키워드", *spelling)
                blogs = self.stored()[0].candidate.blogs
                self.assertEqual(set(blogs), {"naver_a", "naver_b"})
                self.assertEqual(len(blogs), 2)

    def test_add_options_reach_the_candidate(self):
        self.ok("candidates", "add", "--topic", "주제", "--keyword", "키워드", "--blog", "naver_b", "--sub-keywords", "보조 하나, 보조 둘", "--post-type", "비교형", "--reason", "이유", "--data-date", "2026-11-01",
                "--search-demand", "100", "--related-results", "200", "--trend", "하락", "--mobile-share", "55", "--seasonality", "3,4", "--duplicate", "예", "--profile-fit", "10", "--priority", "20",
                "--opportunity", "30")
        candidate = self.stored()[0].candidate
        self.assertEqual((candidate.sub_keywords, candidate.post_type, candidate.reason, candidate.data_date, candidate.search_demand, candidate.related_blog_results, candidate.trend),
                         (("보조 하나", "보조 둘"), "비교형", "이유", "2026-11-01", 100, 200, "하락"))
        self.assertEqual((candidate.mobile_share, candidate.seasonality, candidate.duplicate, candidate.profile_fit, candidate.priority, candidate.keyword_opportunity), (55, (3, 4), True, 10, 20, 30))

    def test_values_the_candidate_rules_refuse_are_handled_errors_that_name_the_column(self):
        for argv, column in ((("--topic", "상위노출 보장 방법", "--keyword", "키워드"), "추천 포스팅 주제"), (("--topic", "주제", "--keyword", "수익 보장"), "핵심 키워드"),
                             (("--topic", "주제", "--keyword", "키워드", "--search-demand", "5"), "데이터 조회일"), (("--topic", "주제", "--keyword", "키워드", "--post-type", "후기"), "추천 글 유형"),
                             (("--topic", "주제", "--keyword", "키워드", "--search-demand", "-5", "--data-date", "2026-11-01"), "월간 검색 수요"), (("--topic", "", "--keyword", "키워드"), "추천 포스팅 주제")):
            with self.subTest(argv=argv):
                err = self.fails("candidates", "add", "--blog", "naver_a", *argv)
                self.assertIn("코드: CANDIDATE_INVALID", err)
                self.assertIn(column, err)
        self.assertFalse(self.root.exists(), "거절된 후보는 아무것도 저장하지 않고 보관함도 만들지 않는다")

    def test_select_hold_reject_review_and_restore_print_what_changed_in_korean(self):
        self.add("가")
        n = self.number(1)
        for argv, needle in ((("select", "1", "--blog", "naver_a"), f"네이버 A 용으로 골랐습니다: [1] 가 (번호 {n}) — 새 후보 → 선택됨"), (("hold", "1"), f"보류했습니다: [1] 가 (번호 {n}) — 선택됨 → 보류"),
                             (("review", "1"), f"검토 중으로 옮겼습니다: [1] 가 (번호 {n}) — 보류 → 검토 중"), (("reject", "1"), f"제외했습니다: [1] 가 (번호 {n}) — 검토 중 → 제외"),
                             (("restore", "1"), f"되살렸습니다: [1] 가 (번호 {n}) — 제외 → 검토 중")):
            with self.subTest(argv=argv):
                out = self.ok("candidates", *argv)
                self.assertIn(needle, out)
                self.assertIsNone(STATUS_CODES.search(out))

    def test_a_move_the_table_does_not_allow_is_a_handled_error_with_korean_state_names_and_changes_nothing(self):
        self.add("가")
        self.ok("candidates", "reject", "1")
        for argv in (("select", "1", "--blog", "naver_a"), ("hold", "1"), ("reject", "1")):
            with self.subTest(argv=argv):
                err = self.fails("candidates", *argv)
                self.assertIn("코드: CANDIDATE_TRANSITION_INVALID", err)
                self.assertIn("제외", err)
                self.assertIsNone(STATUS_CODES.search(err), err)
        err = self.fails("candidates", "restore", "9")
        self.assertIn("CANDIDATE_NOT_FOUND", err)
        self.add("나")
        err = self.fails("candidates", "restore", "2")
        self.assertIn("코드: CANDIDATE_TRANSITION_INVALID", err)
        self.assertIn("새 후보", err)
        self.assertEqual([row.candidate.status for row in self.stored()], [cd.REJECTED, cd.NEW])

    def test_the_second_choice_of_the_same_keyword_for_the_same_blog_warns_in_korean_without_blocking(self):
        self.ctx.settings.save_naver_profile(NaverProfile("naver_a", "블로그 에이", "https://blog.naver.com/exampleaaa", topic_reuse_days=30))
        self.add("주제 하나", "같은 키워드")
        self.add("주제 둘", "같은 키워드")
        self.ok("candidates", "select", "1", "--blog", "naver_a")
        self.ctx.clock.advance(days=12)
        out = self.ok("candidates", "select", "2", "--blog", "naver_a")
        lines = out.splitlines()
        self.assertEqual(lines[0], f"네이버 A 용으로 골랐습니다: [2] 주제 둘 (번호 {self.number(2)}) — 새 후보 → 선택됨")
        self.assertEqual(lines[1], f"주의: 같은 핵심 키워드 「같은 키워드」 을(를) 네이버 A 용으로 12일 전(2026-11-02)에 이미 골랐습니다(순번 1: 주제 하나, 번호 {self.number(1)}). 이 블로그의 같은 주제 재사용 기준은 30일입니다 — 선택은 그대로 기록했습니다.")
        self.assertEqual([row.candidate.status for row in self.stored()], [cd.SELECTED, cd.SELECTED])
        data = self.data("candidates", "select", "2", "--blog", "naver_a")
        self.assertEqual(data["warnings"][0]["days_ago"], 12)
        self.assertTrue(data["again"])

    def test_a_blog_that_was_not_recommended_is_noted(self):
        self.add("가", blog="naver_a")
        out = self.ok("candidates", "select", "1", "--blog", "naver_b")
        self.assertIn("참고: 네이버 B 은(는) 이 후보의 추천 대상 블로그(네이버 A)가 아니지만 요청대로 기록했습니다.", out)

    def test_delete_without_yes_stops_with_the_services_code_and_deletes_nothing(self):
        self.add("지울 후보")
        err = self.fails("candidates", "delete", "1")
        self.assertIn("코드: CONFIRMATION_REQUIRED", err)
        self.assertNotIn("CANDIDATE_CONFIRM_REQUIRED", err)
        n = self.number(1)
        self.assertIn(f"후보 지우기 — 지울 후보 (순번 1, 번호 {n}, 새 후보)", err)
        self.assertIn(f"candidates delete {n} --yes", err, "지울 정확한 명령(번호 앞 8자)을 보여 준다")
        payload = self.error_json("candidates", "delete", "1")
        self.assertEqual((payload["command"], payload["error"]["code"]), ("candidates delete", "CONFIRMATION_REQUIRED"))
        self.assertIn(f"candidates delete {n} --yes", payload["error"]["detail"])
        self.assertEqual(len(self.stored()), 1)
        out = self.ok("candidates", "delete", n, "--yes")
        self.assertEqual(out.splitlines()[0], f"후보를 지웠습니다: [1] 지울 후보 (번호 {n})")
        self.assertIn("순번이 하나씩 당겨졌을 수 있습니다", out)
        self.assertEqual(self.stored(), [])
        self.assertEqual(self.error_json("candidates", "delete", "1", "--yes")["error"]["code"], "CANDIDATE_NOT_FOUND")
        self.assertEqual(self.error_json("candidates", "delete", n, "--yes")["error"]["code"], "CANDIDATE_NOT_FOUND", "같은 명령을 되풀이하면 없다고 알린다")

    def test_a_corrupt_candidate_stops_the_list_with_its_whole_number_and_can_be_deleted_alone_with_that_number(self):
        bad = "bad00000000000000000000000000001"
        self.add("멀쩡한 후보")
        self.ctx.clock.advance(seconds=1)
        with self.ctx.store() as store:
            store.save_candidate(cd.Candidate.new("깨질 후보", "깨질 키워드", ("naver_a",), candidate_id=bad, now=self.ctx.stamp()))
        with closing(sqlite3.connect(str(self.ctx.workspace.store_path), isolation_level=None)) as db:
            db.execute("UPDATE candidates SET data = '{}' WHERE candidate_id = ?", (bad,))
        err = self.fails("candidates", "list")
        self.assertIn("코드: CANDIDATE_CORRUPT", err)
        self.assertIn(bad, err, "오류 세부에 번호 전체가 나온다")
        self.assertIn("코드: CANDIDATE_CORRUPT", self.fails("candidates", "delete", "2", "--yes"))
        preview = self.fails("candidates", "delete", bad)
        self.assertIn("코드: CONFIRMATION_REQUIRED", preview)
        self.assertIn("깨진 후보 지우기 — 번호 bad00000", preview)
        out = self.ok("candidates", "delete", bad, "--yes")
        self.assertEqual(out.splitlines()[0], "후보를 지웠습니다: 번호 bad00000")
        self.assertIn("멀쩡한 후보", self.ok("candidates", "list"))

    def test_link_and_unlink_print_the_post_and_a_missing_post_is_refused(self):
        project_id = projects.new_project(self.ctx, "연결할 글", ss.ko_text()).project_id
        self.add("가")
        out = self.ok("candidates", "link", "1", project_id[:6])
        n = self.number(1)
        self.assertEqual(out.strip(), f"후보와 글을 이었습니다: [1] 가 (번호 {n}) ↔ 연결할 글(글번호 {project_id[:8]})")
        self.assertIn("이미 같은 글과 이어져 있습니다", self.ok("candidates", "link", "1", project_id))
        err = self.fails("candidates", "link", "1", "ffffffff")
        self.assertIn("코드: CONTENT_NOT_FOUND", err)
        self.assertEqual(self.stored()[0].candidate.project_id, project_id)
        self.assertEqual(self.ok("candidates", "unlink", "1").strip(), f"연결을 끊었습니다(글은 그대로입니다): [1] 가 (번호 {n})")
        self.assertIn("이어진 글이 없어 바뀐 것이 없습니다", self.ok("candidates", "unlink", "1"))
        self.assertEqual(self.data("candidates", "link", "1", project_id)["project"]["title"], "연결할 글")


class ImportCommandTest(Base):
    def csv(self, text, name="후보.csv"):
        path = self.tmp / name
        path.write_bytes(text.encode("utf-8"))
        return str(path)

    HEAD = "주제,핵심 키워드,대상 블로그"

    def test_a_clean_file_exits_zero_and_prints_the_summary_and_the_new_numbers(self):
        out = self.ok("candidates", "import-csv", self.csv(self.HEAD + "\n가,키워드 가,naver_a\n나,키워드 나,naver_b\n다,키워드 다,pages\n"))
        self.assertEqual(out.splitlines()[:3], ["가져오기를 마쳤습니다: 후보.csv", "3개 추가·0개 건너뜀·0개 거절", "  추가한 후보(순번): 1~3"])
        self.assertEqual(len(out.splitlines()), 3)

    def test_running_the_same_file_again_still_exits_zero_because_nothing_was_wrong(self):
        path = self.csv(self.HEAD + "\n가,키워드 가,naver_a\n")
        self.ok("candidates", "import-csv", path)
        out = self.ok("candidates", "import-csv", path)
        self.assertIn("0개 추가·1개 건너뜀·0개 거절", out)
        self.assertIn("건너뜀: 줄 2 — 같은 핵심 키워드·주제·블로그의 후보가 이미 있습니다(순번 1)", out)

    def test_a_rejected_line_makes_the_exit_code_one_but_the_rest_is_saved_and_the_reason_is_shown(self):
        path = self.csv("번호," + self.HEAD + ",메모\n1,가,키워드 가,naver_a,x\n2,상위노출 보장 글,키워드 나,naver_a,y\n3,,키워드 다,naver_a,z\n\n4,라,키워드 라,tistory,w\n")
        code, out, err = self.run_cli("candidates", "import-csv", path)
        self.assertEqual((code, err), (1, ""))
        for needle in ("1개 추가·0개 건너뜀·3개 거절", "거절: 줄 3 — 추천 포스팅 주제: ‘상위노출 보장’ 같은 결과를 약속하는 표현은 쓸 수 없습니다", "거절: 줄 4 — 추천 포스팅 주제: 비워 둘 수 없고 200자 이하여야 합니다",
                       "거절: 줄 6 — 추천 대상 블로그: 알 수 없는 블로그 「tistory」", "모르는 열 2개는 무시했습니다: 번호, 메모", "빈 줄 1개는 무시했습니다.", "일부 줄을 거절했습니다"):
            self.assertIn(needle, out)
        self.assertEqual([row.candidate.topic for row in self.stored()], ["가"])
        code, out, err = self.run_cli("--json", "candidates", "import-csv", path)
        payload = json.loads(out)
        self.assertEqual((code, payload["ok"], payload["command"], payload["data"]["summary"]), (1, False, "candidates import-csv", "0개 추가·1개 건너뜀·3개 거절"))
        self.assertEqual([item["line"] for item in payload["data"]["rejected"]], [3, 4, 6])

    def test_a_long_list_of_notes_is_cut_on_screen_and_complete_in_json(self):
        rows = "\n".join(f"상위노출 보장 {n},키워드 {n},naver_a" for n in range(40))
        path = self.csv(self.HEAD + "\n" + rows + "\n")
        code, out, err = self.run_cli("candidates", "import-csv", path)
        self.assertEqual(code, 1)
        self.assertEqual(out.count("거절: 줄 "), 30)
        self.assertIn("거절: … 외 10개(전체는 --json)", out)
        payload = json.loads(self.run_cli("--json", "candidates", "import-csv", path)[1])
        self.assertEqual(len(payload["data"]["rejected"]), 40)

    def test_the_default_blog_and_date_options_fill_the_empty_cells(self):
        path = self.csv("주제,핵심 키워드,월간 검색 수요\n가,키워드 가,500\n")
        code, out, err = self.run_cli("candidates", "import-csv", path)
        self.assertEqual((code, out), (1, ""))
        self.assertIn("대상 블로그 열이 없으면 --blog", err)
        out = self.ok("candidates", "import-csv", path, "--blog", "pages", "--data-date", "2026-11-01")
        self.assertIn("1개 추가", out)
        candidate = self.stored()[0].candidate
        self.assertEqual((candidate.blogs, candidate.data_date, candidate.search_demand), (("github_pages",), "2026-11-01", 500))

    def test_a_file_that_cannot_be_used_is_a_handled_error_that_stores_nothing(self):
        for label, data in (("빈 파일", b""), ("머리줄 없음", "겨울,보일러,naver_a\n".encode("utf-8")), ("UTF-16", "a,b\n".encode("utf-16"))):
            with self.subTest(label=label):
                path = self.tmp / "x.csv"
                path.write_bytes(data)
                err = self.fails("candidates", "import-csv", str(path))
                self.assertIn("코드: CANDIDATE_CSV_INVALID", err)
                self.assertIn("후보 CSV 파일을 가져오지 못했습니다", err)
        err = self.fails("candidates", "import-csv", str(self.tmp / "없는.csv"))
        self.assertIn("CANDIDATE_CSV_INVALID", err)
        self.assertFalse(self.root.exists())
        self.assertEqual(self.error_json("candidates", "import-csv", str(self.tmp / "없는.csv"))["error"]["code"], "CANDIDATE_CSV_INVALID")


class MaskTest(Base):
    def test_a_key_shaped_text_in_a_candidate_never_reaches_the_screen(self):
        self.add("키 모양 " + ss.KEY + " 이 든 주제", "키워드 하나")
        for argv in (("candidates", "list"), ("candidates", "show", "1"), ("--verbose", "candidates", "list"), ("--json", "candidates", "list"), ("--json", "candidates", "show", "1")):
            with self.subTest(argv=argv):
                out = self.ok(*argv)
                self.assertNotIn(ss.KEY, out)
                self.assertIn("[가림", out)
        self.assertNotIn(ss.KEY, self.fails("candidates", "show", ss.KEY))
        self.assertNotIn(ss.KEY, self.fails("candidates", "delete", "1"))

    def test_a_key_shaped_text_in_an_error_is_masked_in_the_json_output_too(self):
        self.add("키 모양 " + ss.KEY + " 이 든 주제", "키워드 하나")
        for argv in (("candidates", "show", ss.KEY), ("candidates", "delete", "1"), ("candidates", "select", ss.KEY, "--blog", "naver_a")):
            with self.subTest(argv=argv):
                payload = self.error_json(*argv)                   # 종료 코드 1·표준 오류 비어 있음·`ok` false 도 함께 확인한다
                shown = json.dumps(payload, ensure_ascii=False)
                self.assertNotIn(ss.KEY, shown)
                self.assertIn("[가림", shown, "가린 자리가 보이지 않으면 시험이 키 모양 글을 만나지도 못한 것이다")

    def test_a_key_shaped_text_in_a_csv_header_or_a_rejected_line_is_masked_too(self):
        path = self.tmp / "x.csv"
        path.write_text("주제,핵심 키워드,대상 블로그,메모 " + ss.KEY + "\n상위노출 보장 " + ss.KEY + ",키워드,naver_a,x\n", encoding="utf-8")
        code, out, err = self.run_cli("candidates", "import-csv", str(path))
        self.assertEqual(code, 1)
        self.assertNotIn(ss.KEY, out + err)
        self.assertIn("[가림", out)
        code, out, err = self.run_cli("--json", "candidates", "import-csv", str(path))
        self.assertNotIn(ss.KEY, out + err)


class DocsTest(unittest.TestCase):
    """문서가 명령·오류 코드·결정과 어긋나지 않게 — 새 하위 명령을 더하고 README·구조 문서를 빠뜨리면 여기서 걸린다."""

    def read(self, name):
        return (ss.ROOT / name).read_text(encoding="utf-8")

    def test_the_readme_and_the_architecture_document_name_every_subcommand(self):
        readme, architecture = self.read("README.md"), self.read("docs/ARCHITECTURE.md")
        for name in SUBCOMMANDS:
            with self.subTest(name=name):
                self.assertIn(name, readme)
                self.assertIn(name, architecture)

    def test_the_new_error_codes_and_the_decision_are_documented_where_they_are_used(self):
        trouble, architecture = self.read("docs/TROUBLESHOOTING.md"), self.read("docs/ARCHITECTURE.md")
        for code in ("CANDIDATE_AMBIGUOUS", "CANDIDATE_CSV_INVALID", "CANDIDATE_DELETE_NEEDS_NUMBER", "PROFILE_INVALID"):
            self.assertIn(code, CATALOG)
            self.assertIn(f"| `{code}` |", trouble)
            self.assertIn(code, architecture)
        self.assertRegex(self.read("docs/DECISIONS.md"), r"(?m)^\| D-23 \|")
        self.assertRegex(self.read("docs/DECISIONS.md"), r"(?m)^\| D-24 \|")
        self.assertIn("D-23", architecture)
        self.assertIn("D-24", architecture)
        self.assertIn("후보 번호가 여러 개와 겹칩니다", CATALOG["CANDIDATE_AMBIGUOUS"].message)


class NoTraceTest(Base):
    def test_every_handled_error_has_no_stack_trace_and_the_exit_code_one(self):
        self.add("가")
        for argv in (("show", "9"), ("select", "9", "--blog", "naver_a"), ("hold", "9"), ("reject", "9"), ("review", "9"), ("restore", "9"), ("delete", "9", "--yes"), ("link", "9", "abcd1234"),
                     ("unlink", "9"), ("show", "abc"), ("import-csv", str(self.tmp / "없는.csv"))):
            with self.subTest(argv=argv):
                err = self.fails("candidates", *argv)
                self.assertIn("코드: ", err)
                self.assertIn("하실 일: ", err)


class DeleteByNumberTest(Base):
    """지우기는 순번이 아니라 번호 앞 8자로 한다 — 순번은 지울 때마다 뒤가 당겨져서, 같은 `delete 3 --yes` 를 되풀이하면 다른 후보가 차례로 지워졌다."""

    def six(self):
        """번호를 정해 둔 후보 여섯 — 앞 4자가 서로 달라 무작위 번호가 우연히 겹쳐 시험이 흔들리지 않는다."""
        with self.ctx.store() as store:
            for index, name in enumerate(("가", "나", "다", "라", "마", "바")):
                self.ctx.clock.advance(seconds=1)
                store.save_candidate(cd.Candidate.new(name, f"키워드 {name}", ("naver_a",), candidate_id=f"{'abcdef'[index]}{index}f{index}e" + "0" * 24, now=self.ctx.stamp()))

    def test_the_same_delete_command_with_an_ordinal_and_yes_deletes_nothing_however_often_it_is_run(self):
        self.six()
        before = [row.candidate.topic for row in self.stored()]
        for repeat in range(3):
            code, out, err = self.run_cli("candidates", "delete", "3", "--yes")
            self.assertEqual((code, out), (1, ""), repeat)
            self.assertIn("코드: CANDIDATE_DELETE_NEEDS_NUMBER", err)
            self.assertIn("순번으로는 지우지 않았습니다", err)
            self.assertIn("후보 지우기 — 다 (순번 3, 번호 " + self.number(3), err, "어느 후보인지 제목과 함께 보여 준다")
            self.assertIn(f"candidates delete {self.number(3)} --yes", err, "지울 명령을 알려 준다")
            self.assertNotIn("Traceback", err)
        self.assertEqual([row.candidate.topic for row in self.stored()], before)
        payload = self.error_json("candidates", "delete", "3", "--yes")
        self.assertEqual(payload["error"]["code"], "CANDIDATE_DELETE_NEEDS_NUMBER")
        self.assertIn(f"candidates delete {self.number(3)} --yes", payload["error"]["detail"])

    def test_a_short_beginning_with_yes_deletes_nothing_either(self):
        self.six()
        number = self.number(3)
        for text in (number[:4], number[:7]):
            with self.subTest(text=text):
                err = self.fails("candidates", "delete", text, "--yes")
                self.assertIn("CANDIDATE_DELETE_NEEDS_NUMBER", err)
        self.assertEqual(len(self.stored()), 6)

    def test_the_command_the_error_names_deletes_exactly_that_candidate_once(self):
        self.six()
        number = self.number(3)
        out = self.ok("candidates", "delete", number, "--yes")
        self.assertEqual(out.splitlines()[0], f"후보를 지웠습니다: [3] 다 (번호 {number})")
        self.assertEqual([row.candidate.topic for row in self.stored()], ["가", "나", "라", "마", "바"])
        for repeat in range(2):
            self.assertEqual(self.error_json("candidates", "delete", number, "--yes")["error"]["code"], "CANDIDATE_NOT_FOUND", repeat)
        self.assertEqual(len(self.stored()), 5, "같은 명령을 되풀이해도 다른 후보는 안 지워진다")

    def test_the_preview_without_yes_takes_an_ordinal_and_names_the_command_with_the_number(self):
        self.six()
        err = self.fails("candidates", "delete", "4")
        self.assertIn("코드: CONFIRMATION_REQUIRED", err)
        self.assertIn(f"candidates delete {self.number(4)} --yes", err)
        self.assertIn("순번으로는 지우지 않습니다", err)
        self.assertEqual(len(self.stored()), 6)

    def test_the_help_says_to_use_the_number_and_not_the_ordinal_for_deleting(self):
        for argv, needles in ((("candidates", "delete", "--help"), ("지울 후보의 번호 앞 8자", "순번은 지울 때마다 당겨져서", "--yes")), (("candidates", "--help"), ("지울 때는 순번이 아니라", "'번호'(앞 8자)", "candidates delete 번호 --yes"))):
            with self.subTest(argv=argv):
                code, out, err = self.run_cli(*argv)
                self.assertEqual((code, err), (0, ""))
                squeezed = " ".join(out.split())
                for needle in needles:
                    self.assertIn(needle, squeezed)
                self.assertNotIn("지울 후보의 순번", squeezed, "도움말이 순번으로도 지운다고 하지 않는다")
                self.assertNotIn("순번이나 번호 앞 8자", squeezed)

    def test_a_corrupt_candidate_is_deleted_by_the_eight_characters_the_error_shows(self):
        bad = "bad00000000000000000000000000001"
        self.add("멀쩡한 후보")
        self.ctx.clock.advance(seconds=1)
        with self.ctx.store() as store:
            store.save_candidate(cd.Candidate.new("깨질 후보", "깨질 키워드", ("naver_a",), candidate_id=bad, now=self.ctx.stamp()))
        with closing(sqlite3.connect(str(self.ctx.workspace.store_path), isolation_level=None)) as db:
            db.execute("UPDATE candidates SET data = '{}' WHERE candidate_id = ?", (bad,))
        err = self.fails("candidates", "list")
        self.assertIn("후보 번호 「bad00000」", err, "오류 문구에는 번호 앞 8자가 나온다")
        self.assertIn("candidates delete 번호 --yes", err, "오류 안내가 지우는 방법을 알려 준다")
        preview = self.fails("candidates", "delete", "bad00000")
        self.assertIn("코드: CONFIRMATION_REQUIRED", preview)
        self.assertIn("candidates delete bad00000 --yes", preview)
        self.assertIn("코드: CANDIDATE_CORRUPT", self.fails("candidates", "delete", "bad0", "--yes"), "짧은 앞부분으로는 못 지운다")
        out = self.ok("candidates", "delete", "bad00000", "--yes")
        self.assertEqual(out.splitlines()[0], "후보를 지웠습니다: 번호 bad00000")
        self.assertIn("멀쩡한 후보", self.ok("candidates", "list"))


class ManyCandidatesTest(Base):
    def many(self):
        """후보 1005개 — 번호를 정해 저장한다(무작위 번호가 우연히 '1005' 로 시작해 시험이 흔들리지 않게)."""
        with self.ctx.store() as store:
            stamp = self.ctx.stamp()
            store.add_candidates(lambda existing: [cd.Candidate.new(f"대량 주제 {n:04d}", f"대량키워드{n:04d}", ("naver_a",), candidate_id=f"zz{n:06d}", now=stamp) for n in range(1005)])

    def test_the_limit_note_appears_exactly_when_a_shown_row_has_an_ordinal_of_1000_or_more(self):
        self.many()
        for ordinal, noted in ((998, False), (999, False), (1000, True), (1001, True)):
            with self.subTest(ordinal=ordinal):
                number = self.number(ordinal)
                self.ok("candidates", "hold", number)
                held = self.ok("candidates", "list", "--status", "보류")
                self.assertIn(f"  [{ordinal}] 보류", held)
                self.assertEqual("순번 1000 이상은 순번으로 고를 수 없습니다" in held, noted)
                self.ok("candidates", "review", number)

    def test_past_999_the_list_shows_every_number_and_an_ordinal_of_1000_or_more_is_explained_instead_of_just_missing(self):
        self.many()
        listing = self.ok("candidates", "list").splitlines()
        self.assertEqual(len(listing), 1 + 1005 + 3)
        last = listing[1005]
        self.assertTrue(last.startswith("  [1005] 새 후보 — 대량 주제 1004 "), last)
        number = last.rsplit("번호 ", 1)[1]
        self.assertEqual(number, self.number(1005))
        self.assertEqual(len(number), 8)
        self.assertIn("순번 1000 이상은 순번으로 고를 수 없습니다", listing[-1])
        self.assertIn("번호 앞 8자로 고릅니다", listing[-1])
        err = self.fails("candidates", "show", "1005")
        self.assertIn("코드: CANDIDATE_NOT_FOUND", err)
        self.assertIn("1000번 이상은 순번으로 고를 수 없습니다 — 번호 앞 8자로 고르세요", err)
        self.assertIn("대량 주제 1004", self.ok("candidates", "show", number))
        self.assertIn("대량 주제 0998", self.ok("candidates", "show", "999"), "999번까지는 순번으로 고른다")
        self.assertEqual(self.ok("candidates", "hold", number).splitlines()[0], f"보류했습니다: [1005] 대량 주제 1004 (번호 {number}) — 새 후보 → 보류")
        held = self.ok("candidates", "list", "--status", "보류").splitlines()
        self.assertEqual(held[1], f"  [1005] 보류 — 대량 주제 1004 · 핵심 키워드: 대량키워드1004 · 대상: 네이버 A · 번호 {number}")
        self.assertIn("순번 1000 이상은 순번으로 고를 수 없습니다", held[-1], "거른 목록에도 1000번 이상이 보이면 알려 준다")
        self.assertNotIn("순번 1000 이상은", self.ok("candidates", "list", "--status", "선택"), "보이는 줄에 1000번 이상이 없으면 말하지 않는다")

    def test_a_list_with_fewer_than_a_thousand_does_not_mention_the_limit(self):
        self.add("가")
        self.assertNotIn("1000", self.ok("candidates", "list"))


class DisplayDetailsTest(Base):
    def test_the_status_word_review_means_in_review_not_hold_and_the_other_short_words_too(self):
        for name in ("가", "나", "다", "라"):
            self.add(name)
        self.ok("candidates", "hold", "2")
        self.ok("candidates", "select", "3", "--blog", "naver_a")
        self.ok("candidates", "review", "2")
        self.ok("candidates", "hold", "1")

        def shown(*argv):
            return [item["ordinal"] for item in self.data("candidates", "list", *argv)["candidates"]]

        self.assertEqual(shown("--status", "검토"), [2])
        self.assertEqual(shown("--status", "검토 중"), [2])
        self.assertEqual(shown("--status", "보류"), [1])
        self.assertEqual(shown("--status", "선택"), [3])
        self.assertEqual(shown("--status", "새 후보"), [4])

    def test_show_prints_the_creation_time_before_the_last_edit_time_in_korean_time(self):
        self.add("가")
        self.assertEqual(self.ctx.stamp(), "2026-11-02T01:30:13Z")
        self.ctx.clock.advance(days=2, hours=15)                      # 협정세계시 11월 4일 16:30 — 한국 시간으로는 11월 5일 01:30
        self.ok("candidates", "hold", "1")
        out = self.ok("candidates", "show", "1")
        self.assertIn("  만든 때: 2026-11-02 10:30   고친 때: 2026-11-05 01:30   (한국 시간)", out)
        self.ok("candidates", "review", "1")
        self.ok("candidates", "select", "1", "--blog", "naver_a")
        self.assertIn("  네이버 A 용으로 고른 때: 2026-11-05 01:30", self.ok("candidates", "show", "1"))
        stored = self.data("candidates", "show", "1")["candidate"]
        self.assertEqual((stored["created_at"], stored["updated_at"], stored["selections"]), ("2026-11-02T01:30:13Z", "2026-11-04T16:30:13Z", {"naver_a": "2026-11-04T16:30:13Z"}), "저장한 값은 협정세계시 그대로다")

    def test_show_names_the_number_right_under_the_title_and_the_whole_number_only_with_verbose(self):
        self.add("가")
        candidate_id = self.stored()[0].candidate.candidate_id
        lines = self.ok("candidates", "show", "1").splitlines()
        self.assertEqual(lines[0], "후보 [1]: 가")
        self.assertEqual(lines[1], f"  번호: {candidate_id[:8]}   (순번은 후보를 지우면 바뀔 수 있고 번호는 바뀌지 않습니다)")
        verbose = self.ok("--verbose", "candidates", "show", "1").splitlines()
        self.assertEqual(verbose[1], f"  번호: {candidate_id}   (순번은 후보를 지우면 바뀔 수 있고 번호는 바뀌지 않습니다)")
        self.assertIn("  판: 1", verbose)

    def test_choosing_for_a_second_blog_says_that_only_the_choice_record_was_added(self):
        self.add("가", blog="naver_a,naver_b")
        self.ok("candidates", "select", "1", "--blog", "naver_a")
        out = self.ok("candidates", "select", "1", "--blog", "naver_b")
        self.assertIn(f"네이버 B 용으로도 골랐습니다: [1] 가 (번호 {self.number(1)}) — 이미 선택됨이어서 선택 기록만 더했습니다", out)
        self.assertNotIn("새 후보 → 선택됨", out)

    def test_every_result_line_that_names_a_candidate_names_its_number_too(self):
        project_id = projects.new_project(self.ctx, "연결할 글", ss.ko_text()).project_id
        self.add("가")
        n = self.number(1)
        for argv in (("select", "1", "--blog", "naver_a"), ("hold", "1"), ("review", "1"), ("reject", "1"), ("restore", "1"), ("hold", "1"), ("link", "1", project_id), ("unlink", "1")):
            with self.subTest(argv=argv):
                self.assertIn(f"(번호 {n})", self.ok("candidates", *argv).splitlines()[0])
        self.assertIn(f"번호 {n}", self.ok("candidates", "delete", n, "--yes").splitlines()[0])


class DoctorAndRecoveryTest(Base):
    def corrupt(self, count=1):
        ids = []
        for index in range(count):
            self.add(f"깨질 후보 {index}")
            ids.append(self.stored()[-1].candidate.candidate_id)
        with closing(sqlite3.connect(str(self.ctx.workspace.store_path), isolation_level=None)) as db:
            for candidate_id in ids:
                db.execute("UPDATE candidates SET data = '{}' WHERE candidate_id = ?", (candidate_id,))
        return ids

    def store_line(self, out):
        return next(line for line in out.splitlines() if "글 저장소" in line)

    def test_a_corrupt_candidate_is_reported_as_that_candidate_with_the_command_to_delete_it_not_as_a_broken_store(self):
        (bad,) = self.corrupt()
        code, out, err = self.run_cli("doctor")
        self.assertEqual(code, 1)
        line = self.store_line(out)
        self.assertIn("[실패]", line)
        self.assertIn(f"주제 후보 1개가 깨져 있습니다(번호 {bad[:8]})", line)
        self.assertIn("글과 다른 후보는 이상 없습니다", line)
        self.assertIn("CANDIDATE_CORRUPT", line)
        self.assertIn(f"candidates delete {bad[:8]} --yes", out)
        self.assertIn("저장소 파일을 이름 바꿔 새로 시작할 필요는 없습니다", out)
        self.assertNotIn("STORE_CORRUPT", out)
        code, out, err = self.run_cli("--json", "doctor")
        self.assertEqual((code, err), (1, ""))
        checks = {item["name"]: item for item in json.loads(out)["data"]["checks"]}
        self.assertEqual((checks["글 저장소"]["status"], checks["글 저장소"]["code"]), ("fail", "CANDIDATE_CORRUPT"))

    def test_several_corrupt_candidates_are_counted_and_the_first_few_are_named(self):
        ids = self.corrupt(7)
        line = self.store_line(self.run_cli("doctor")[1])
        self.assertIn("주제 후보 7개가 깨져 있습니다", line)
        ordered = sorted(ids)                                                # 점검은 번호 순으로 짚는다
        for candidate_id in ordered[:5]:
            self.assertIn(candidate_id[:8], line)
        for candidate_id in ordered[5:]:
            self.assertNotIn(candidate_id[:8], line)
        self.assertIn("외 2개", line)

    def test_several_problems_of_one_candidate_count_that_candidate_once(self):
        self.add("가")
        with mock.patch.object(Store, "check", return_value=["후보 aaaa1111: 하나", "후보 aaaa1111: 둘", "후보 bbbb2222: 셋"]):
            code, out, err = self.run_cli("doctor")
        self.assertEqual(code, 1)
        self.assertIn("주제 후보 2개가 깨져 있습니다(번호 aaaa1111, bbbb2222)", self.store_line(out))
        self.assertIn("candidates delete aaaa1111 --yes", out)

    def test_a_problem_that_is_not_a_candidates_keeps_the_whole_store_message(self):
        self.add("가")
        for problems in (["파일 구조: 시험용"], ["후보 abc1: 시험용", "파일 구조: 시험용"], ["프로젝트 p1: 시험용"]):
            with self.subTest(problems=problems):
                with mock.patch.object(Store, "check", return_value=problems):
                    code, out, err = self.run_cli("doctor")
                self.assertEqual(code, 1)
                self.assertIn("STORE_CORRUPT", self.store_line(out))
                self.assertIn("점검에서 문제", self.store_line(out))
                self.assertNotIn("CANDIDATE_CORRUPT", out)

    def test_a_healthy_store_has_no_candidate_complaint(self):
        self.add("가")
        self.assertIn("이상 없습니다", self.store_line(self.run_cli("doctor")[1]))

    def test_a_save_the_app_left_unfinished_tells_which_commands_clean_it_up(self):
        self.add("가")
        journal = Path(str(self.ctx.workspace.store_path) + "-journal")
        journal.write_bytes(b"\x01" * 16)
        with mock.patch.object(Store, "_verify", side_effect=sqlite3.OperationalError("attempt to write a readonly database")):
            for argv in (("candidates", "list"), ("candidates", "show", "1")):
                with self.subTest(argv=argv):
                    err = self.fails(*argv)
                    self.assertIn("코드: STORE_RECOVERY_PENDING", err)
                    squeezed = " ".join(err.split())
                    for needle in ("한 번 열면", "`list`", "`candidates add", "읽기만 해서 정리하지 못합니다"):
                        self.assertIn(needle, squeezed)


if __name__ == "__main__":
    unittest.main()
