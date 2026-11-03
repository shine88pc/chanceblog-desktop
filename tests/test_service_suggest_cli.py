"""명령줄 `candidates suggest`·`candidates list --priority`·`candidates show` 우선도 시험(같은 프로세스에서 돌린다 — 진짜 프로세스 시험은 test_service_suggest_process.py).

지키는 것:
  1) 종료 코드: 0 정상(프로필이 비어 있어도 안내와 함께 0) · 1 처리된 오류(`SUGGESTION_NOT_FOUND` …) · 2 사용법 오류(`--count 0`·`--month 13`·`--yes` 만·블로그가 둘인데 `--blog` 없이 `--add`). 사용법 오류 문구에 친 값이 나오지 않는다.
  2) 화면에는 영문 상태 코드·긴 번호가 없고, 결과 표현은 정해진 이름(콘텐츠 작성 우선도·블로그 프로필 적합도·키워드 기회도 …)만 쓰며 순위·확률·노출을 약속하는 말이 없다. 키 모양 문자열은 글·`--json`·`--verbose` 모두 가려진다.
  3) `list --priority`·`show` 는 읽기만 하고(데이터 폴더가 그대로) `--priority` 가 없으면 `list` 의 출력·JSON 은 한 글자도 바뀌지 않는다. `suggest` 는 읽기만 하고, `--add` 는 `--yes` 없이는 넣지 않는다.
  4) 화면의 '넣으려면' 안내 명령을 그대로 실행하면 그 제안들이 들어간다.
"""
import json
import re
import shlex
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import service_support as ss  # noqa: E402
import suggest_support as sp  # noqa: E402

from chanceblog_desktop.content import candidates as cd  # noqa: E402
from chanceblog_desktop.content.store import Store  # noqa: E402
from chanceblog_desktop.errors import CATALOG  # noqa: E402
from chanceblog_desktop.service import candidates as cands  # noqa: E402

STATUS_CODES = re.compile(r"\b(?:NEW|REVIEW|SELECTED|HOLD|REJECTED)\b")
LONG_ID = re.compile(r"\b[0-9a-f]{32}\b")
BANNED = ("상위노출", "노출 확률", "검색 1위", "수익 보장", "확률", "순위", "랭킹", "보장합니다")


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.ctx = ss.make_ctx(self.tmp, repo="")
        self.root = self.ctx.workspace.root
        self.ctx.settings.save_naver_profile(sp.rich())

    def run_cli(self, *argv):
        return ss.run_cli(self.ctx, *argv)

    def ok(self, *argv):
        code, out, err = self.run_cli(*argv)
        self.assertEqual((code, err), (0, ""), (argv, out, err))
        return out

    def data(self, *argv):
        payload = json.loads(self.ok("--json", *argv))
        self.assertTrue(payload["ok"], payload)
        return payload["data"]

    def fails(self, *argv, code=1):
        got, out, err = self.run_cli(*argv)
        self.assertEqual((got, out), (code, ""), (argv, out, err))
        self.assertNotIn("Traceback", err)
        return err

    def state(self):
        return None if not self.root.exists() else {path.relative_to(self.root).as_posix(): (path.read_bytes(), path.stat().st_mtime_ns) for path in sorted(self.root.rglob("*")) if path.is_file()}

    def stored(self):
        with Store.open(self.ctx.workspace.store_path, migrate=False) as store:
            return store.list_candidates()


class SuggestOutputTest(Base):
    def test_the_default_run_prints_the_header_the_seeds_ten_suggestions_and_the_notes(self):
        out = self.ok("candidates", "suggest")
        lines = out.splitlines()
        self.assertEqual(lines[0], "네이버 A(블로그 에이) 주제 제안 — 11월 기준 · 계산일 2026-11-02")
        self.assertIn("씨앗: 생활 절약(주제) · 보일러 난방(주제) · 가계부(주제)", out)
        ranks = re.findall(r"^  \[(\d+)\] 콘텐츠 작성 우선도 (높음|보통|낮음) [0-9.]+점 · 블로그 프로필 적합도 [0-9.]+ · (\S+(?: \S+)*) · 데이터 없음$", out, re.M)
        self.assertEqual([int(rank) for rank, _level, _type in ranks][:3], [1, 2, 3])
        self.assertEqual(len(ranks), 10)
        for label in ("      주제: ", "      핵심 키워드: ", "      이유: "):
            self.assertEqual(out.count(label), 10)
        self.assertIn("외부 데이터가 없어 키워드 기회도는 반영하지 않았습니다", out)
        self.assertIn("\n\n점수는 이 프로그램이 가진 정보로 정한 작성 순서의 참고값입니다", out, "제안 목록과 점수 안내 사이는 빈 줄로 나뉜다")
        self.assertIn("알려 둔 한계: 기존 글 확인은 보관함의 원고 제목과 고른 후보의 주제를 기준으로 합니다", out)
        self.assertIn("넣으려면: `python -m chanceblog_desktop candidates suggest --blog naver_a --add 1,2,3 --yes`", out)

    def test_nothing_in_the_output_is_an_english_code_a_long_number_or_a_promise_of_results(self):
        for argv in (("candidates", "suggest"), ("candidates", "suggest", "--verbose"), ("candidates", "suggest", "--count", "50", "--month", "7")):
            out = self.ok(*argv)
            self.assertIsNone(STATUS_CODES.search(out), argv)
            self.assertIsNone(LONG_ID.search(out), argv)
            self.assertEqual([word for word in BANNED if word in out], [], argv)
            for line in out.splitlines():
                self.assertIsNone(cd.forbidden_claim(line), line)

    def test_each_option_changes_the_result_the_documented_way(self):
        count = self.data("candidates", "suggest", "--count", "3")["blogs"][0]
        self.assertEqual(len(count["suggestions"]), 3)
        month = self.data("candidates", "suggest", "--month", "7", "--count", "30")["blogs"][0]
        self.assertEqual(month["month"], 7)
        self.assertTrue(all("7월" in item["reason"] for item in month["suggestions"] if item["season"] is not None))
        for spelling in ("비교형", "비교", "비교 형"):
            kind = self.data("candidates", "suggest", "--type", spelling, "--count", "30")["blogs"][0]
            self.assertTrue(kind["suggestions"], spelling)
            self.assertEqual({item["post_type"] for item in kind["suggestions"]}, {"비교형"}, spelling)
        for spelling in ("naver_a", "네이버 A", "네이버A"):
            self.assertEqual([group["blog"] for group in self.data("candidates", "suggest", "--blog", spelling)["blogs"]], ["naver_a"], spelling)

    def test_removed_and_hidden_counts_are_printed_on_their_own_lines_with_their_own_reasons(self):
        self.ctx.settings.save_naver_profile(sp.rich(excluded_topics=("보험",)))
        wanted = self.data("candidates", "suggest")["blogs"][0]["suggestions"][0]["keyword"]
        cands.add_candidate(self.ctx, topic="이미 있는 후보", keyword=wanted, blogs=("naver_a",))
        out = self.ok("candidates", "suggest")
        removed = [line for line in out.splitlines() if line.startswith("걸러낸 조합(만든 ")]
        hidden = [line for line in out.splitlines() if line.startswith("숨긴 제안(번호는 그대로입니다): ")]
        self.assertEqual(len(removed), 1)
        self.assertEqual(len(hidden), 1)
        self.assertRegex(removed[0], r"^걸러낸 조합\(만든 \d+개 중\): 제외어 \d+$")
        self.assertEqual(hidden[0], "숨긴 제안(번호는 그대로입니다): 보관함에 이미 있음 1")
        self.assertNotIn("보관함에 이미 있음", removed[0])
        self.assertNotIn("제외어", hidden[0])

    def test_verbose_adds_the_calculation_line_to_each_suggestion(self):
        plain = self.ok("candidates", "suggest")
        verbose = self.ok("candidates", "suggest", "--verbose")
        self.assertNotIn("계산 내역", plain)
        self.assertEqual(verbose.count("      계산 내역: 씨앗 「"), 10)
        self.assertIn("fit 100×35.3%", verbose)

    def test_a_profile_without_topics_prints_the_guidance_with_exit_code_zero(self):
        empty = ss.make_ctx(self.tmp / "비어 있는 곳", repo="")
        code, out, err = ss.run_cli(empty, "candidates", "suggest")
        self.assertEqual((code, err), (0, ""))
        self.assertIn("프로필에 주제를 적어 주세요", out)
        self.assertIn("naver-profile set naver_a --topic", out)
        self.assertNotIn("[1]", out)
        payload = json.loads(ss.run_cli(empty, "--json", "candidates", "suggest")[1])
        self.assertEqual((payload["ok"], payload["data"]["blogs"][0]["suggestions"], payload["data"]["blogs"][0]["guidance"]), (True, [], payload["data"]["blogs"][0]["guidance"]))
        self.assertTrue(payload["data"]["blogs"][0]["guidance"])

    def test_when_every_seed_is_dropped_the_screen_and_the_add_error_still_say_how_many_were_not_used(self):
        """씨앗이 전부 버려져 제안이 하나도 없어도 몇 개를 왜 버렸는지 알린다 — 독립 검증 2차의 중간 1건(전에는 '주제를 적어 주세요' 안내만 나오고 이유가 빠졌고 `--json` 에만 있었다)."""
        cases = (("맛집 후기, 내돈내산 청소기, 무조건 합격", "겪은 일이나 결과·수익의 보장을 뜻하는 낱말이 든 씨앗 3개는 쓰지 않았습니다"),
                 ("AKIAIOSFODNN7EXAMPLE", "비밀 모양의 글이 든 씨앗 1개는 쓰지 않았습니다"))
        for topic, note in cases:
            with self.subTest(topic=topic[:6]):
                self.ctx.settings.save_naver_profile(sp.profile(topic=topic))
                out = self.ok("candidates", "suggest", "--blog", "naver_a")
                self.assertIn("프로필에 주제를 적어 주세요", out)
                self.assertIn("참고: " + note, out)
                err = self.fails("candidates", "suggest", "--blog", "naver_a", "--add", "1")
                self.assertIn(note, err)
                by_keyword = self.fails("candidates", "suggest", "--blog", "naver_a", "--add", "겨울 난방")      # 키워드로 찾는 경로도 같은 이유를 싣는다
                self.assertIn(note, by_keyword)
                for shown in (out, err, by_keyword):
                    for typed in ("내돈내산", "AKIA", "무조건 합격"):
                        self.assertNotIn(typed, shown)                # 친 글은 화면에도 오류에도 싣지 않는다
                notes = self.data("candidates", "suggest", "--blog", "naver_a")["blogs"][0]["notes"]
                self.assertTrue(any(note in line for line in notes), notes)

    def test_two_profiles_print_two_sections_and_a_non_naver_blog_says_it_has_no_profile_store(self):
        self.ctx.settings.save_naver_profile(sp.rich("naver_b", topic="여행 계획, 맛집"))
        out = self.ok("candidates", "suggest", "--count", "2")
        self.assertIn("네이버 A(블로그 에이) 주제 제안", out)
        self.assertIn("네이버 B(블로그 비) 주제 제안", out)
        self.assertEqual(out.count("\n\n네이버 B"), 1)
        other = self.ok("candidates", "suggest", "--blog", "github_pages")
        self.assertIn("GitHub Pages 주제 제안", other)
        self.assertIn("프로필(주제·카테고리)을 저장해 두는 곳이 아직 없어", other)

    def test_the_json_shape(self):
        data = self.data("candidates", "suggest", "--count", "2")
        self.assertEqual(set(data), {"blogs", "store", "limits"})
        self.assertEqual(data["store"], "missing")
        group = data["blogs"][0]
        self.assertEqual(set(group), {"blog", "month", "today", "count", "suggestions", "generated", "filtered", "hidden_ranks", "seeds", "seed_total", "guidance", "notes", "post_type", "profile_name"})
        item = group["suggestions"][0]
        self.assertEqual(set(item), {"rank", "blog", "keyword", "sub_keywords", "topic", "post_type", "reason", "priority", "profile_fit", "season", "metrics", "data_date", "computed_on", "data", "data_text",
                                     "seed", "seed_source", "frame", "factors"})
        self.assertEqual(set(item["priority"]), {"level", "score"})
        self.assertEqual(item["metrics"], {"search_demand": None, "related_blog_results": None, "trend": None, "seasonality": None, "mobile_share": None})
        self.assertEqual((item["data_date"], item["computed_on"], item["data"]), (None, "2026-11-02", {"data_date": None, "days_ago": None, "stale": False, "future": False}))
        self.assertEqual({entry["name"] for entry in item["factors"]}, {"fit", "season", "freshness", "balance"})
        self.assertTrue(item["data_text"].startswith("계산일 2026-11-02 — 외부 데이터 없음"))
        self.assertEqual(group["profile_name"], "블로그 에이")

    def test_a_key_shaped_text_is_masked_everywhere_it_could_show_up(self):
        from chanceblog_desktop.content.profiles import NaverProfile
        self.ctx.settings.save_naver_profile(NaverProfile("naver_a", "이름 " + ss.KEY, "https://blog.naver.com/exampleaaa", topic="가계부, 절약"))       # 프로필의 표시명이 키 모양이어도
        cands.add_candidate(self.ctx, topic="키 모양 " + ss.KEY + " 주제", keyword="가계부 키워드", blogs=("naver_a",))
        for argv in (("candidates", "suggest"), ("--verbose", "candidates", "suggest"), ("--json", "candidates", "suggest"), ("candidates", "list", "--priority"), ("--json", "candidates", "list", "--priority"),
                     ("candidates", "show", "1"), ("--json", "candidates", "show", "1"), ("--verbose", "candidates", "show", "1"), ("candidates", "suggest", "--blog", "naver_a", "--add", "1")):
            out = self.ok(*argv)
            self.assertNotIn(ss.KEY, out, argv)
        self.assertIn("[가림", self.ok("candidates", "list", "--priority"))
        self.assertIn("[가림", self.ok("candidates", "suggest"))


class FormatTest(unittest.TestCase):
    def test_an_assessment_without_a_priority_is_printed_as_nothing_to_compute(self):
        from unittest import mock
        from chanceblog_desktop.content import suggest as sg
        from chanceblog_desktop.content import suggest_score as sc
        from chanceblog_desktop.service import format as fmt
        with mock.patch.object(sc, "combine", return_value=(None, ())):
            found = sg.assess(sp.make("보일러 난방"), profile=sp.rich(), today=sp.TODAY)
        self.assertEqual(fmt.priority_suffix(found), " · 콘텐츠 작성 우선도: 계산할 정보 없음")
        lines = fmt.assessment_lines(found)
        self.assertEqual(lines[0], "  계산한 콘텐츠 작성 우선도: 계산할 정보가 없습니다")
        self.assertNotIn("왜 이 우선도인지", "\n".join(lines))


    def test_a_suggestion_outside_the_numbered_list_is_labelled_so_and_not_as_number_zero(self):
        from dataclasses import replace
        from chanceblog_desktop.content import suggest as sg
        from chanceblog_desktop.service import format as fmt
        from chanceblog_desktop.service import suggestions as svc
        found = sg.suggest(sp.profile(topic="난방"), today=sp.TODAY, count=2).suggestions[0]
        outside = replace(found, rank=0)
        text = " | ".join(fmt.suggest_add_lines(svc.AddResult("naver_a", False, (svc.AddItem(outside, "키워드", "add"),), (), ())))
        self.assertIn("넣을 제안 [목록 밖] ", text)
        self.assertNotIn("[0]", text)
        text = " | ".join(fmt.suggest_add_lines(svc.AddResult("naver_a", False, (svc.AddItem(outside, "키워드", "skip", "이미 보관함에 있습니다"),), (), ())))
        self.assertIn("건너뜀 [목록 밖] ", text)
        self.assertNotIn("[0]", text)


class UsageTest(Base):
    def test_the_number_options_take_ascii_digits_only(self):
        for flag, bad in (("--count", ("1_0", "１０", "+5", "٣", "0", "51", "1e1")), ("--month", ("1_1", "１１", "+5", "٣", "13", "0"))):
            for value in bad:
                err = self.fails("candidates", "suggest", "--blog", "naver_a", flag, value, code=2)
                if value in ("1_0", "1_1", "+5", "1e1"):
                    self.assertNotIn(value, err, "친 값을 되풀이하지 않는다")
        self.ok("candidates", "suggest", "--blog", "naver_a", "--count", "5", "--month", "12")

    def test_wrong_option_values_are_usage_errors_with_a_korean_message_and_no_echo(self):
        secret = ss.KEY
        cases = (("--count", "0", "1~50"), ("--count", "51", "1~50"), ("--count", secret, "1~50"), ("--count", "-3", "1~50"), ("--month", "0", "1~12"), ("--month", "13", "1~12"), ("--month", secret, "1~12"),
                 ("--type", "소설", "다음 중 하나"), ("--type", secret, "다음 중 하나"), ("--add", "", "적어야"), ("--add", "all,1", "all 은"), ("--add", "0", "1 이상"), ("--add", "5-2", "범위"), ("--blog", "tistory", "블로그"), ("--blog", secret, "알 수 없는 블로그"))
        for flag, value, words in cases:
            code, out, err = self.run_cli("candidates", "suggest", flag, value)
            with self.subTest(flag=flag, value=value[:12]):
                self.assertEqual((code, out), (2, ""))
                self.assertIn("사용법 오류", err)
                self.assertIn(words, err)
                self.assertNotIn(secret, err)
                self.assertNotIn(secret[:12], err, "앞부분만이라도 오류 문구에 싣지 않는다")
                self.assertNotIn("Traceback", err)

    def test_yes_alone_and_add_without_a_single_blog_are_usage_errors(self):
        err = self.fails("candidates", "suggest", "--yes", code=2)
        self.assertIn("--yes 는 --add 와 함께 씁니다", err)
        self.ctx.settings.save_naver_profile(sp.rich("naver_b", topic="여행 계획"))
        err = self.fails("candidates", "suggest", "--add", "1", code=2)
        self.assertIn("--blog 로 블로그를 하나 정합니다", err)
        self.assertEqual(self.state() is None or not self.ctx.workspace.store_path.exists(), True)

    def test_add_with_no_saved_profile_at_all_says_so(self):
        empty = ss.make_ctx(self.tmp / "비어 있는 곳", repo="")
        code, out, err = ss.run_cli(empty, "candidates", "suggest", "--add", "1")
        self.assertEqual((code, out), (2, ""))
        self.assertIn("프로필이 저장된 네이버 블로그가 아직 없습니다", err)

    def test_a_number_that_is_not_in_the_list_is_a_handled_error_with_the_code_and_the_next_step(self):
        err = self.fails("candidates", "suggest", "--blog", "naver_a", "--add", "99", "--yes")
        self.assertIn("코드: SUGGESTION_NOT_FOUND", err)
        self.assertIn("--add 의 1번째 값", err)
        self.assertIn("하실 일:", err)
        self.assertFalse(self.ctx.workspace.store_path.exists())
        payload = json.loads(self.run_cli("--json", "candidates", "suggest", "--blog", "naver_a", "--add", "99")[1])
        self.assertEqual((payload["ok"], payload["command"], payload["error"]["code"]), (False, "candidates suggest", "SUGGESTION_NOT_FOUND"))

    def test_the_new_error_code_is_in_the_catalog_with_a_plain_action(self):
        entry = CATALOG["SUGGESTION_NOT_FOUND"]
        self.assertIn("제안 목록에서 찾을 수 없는 값", entry.message)
        self.assertIn("candidates suggest", entry.action)

    def test_help_for_suggest_is_korean_and_lists_every_option(self):
        code, out, err = self.run_cli("candidates", "suggest", "--help")
        self.assertEqual((code, err), (0, ""))
        for needle in ("사용법:", "--blog", "--count", "--month", "--type", "--add", "--yes", "읽기만 합니다", "프로필에 주제가 없으면", "같은 키워드가 겹치지 않습니다"):
            self.assertIn(needle, out)
        for word in ("usage:", "positional arguments", "options:"):
            self.assertNotIn(word, out)
        self.assertIn("suggest", self.run_cli("candidates", "--help")[1])


class AddOutputTest(Base):
    def test_without_yes_the_preview_lists_what_would_go_in_and_changes_nothing(self):
        before = self.state()
        out = self.ok("candidates", "suggest", "--blog", "naver_a", "--add", "1,2")
        self.assertIn("제안 넣기 미리 보기 — 네이버 A(아무것도 넣지 않았습니다)", out)
        self.assertEqual(len(re.findall(r"^  넣을 제안 \[\d\] ", out, re.M)), 2)
        self.assertIn("같은 명령 끝에 --yes 를 붙이면", out)
        self.assertEqual(self.state(), before)
        data = self.data("candidates", "suggest", "--blog", "naver_a", "--add", "1,2")
        self.assertEqual((data["confirmed"], data["added"], len(data["items"])), (False, [], 2))

    def test_with_yes_they_go_in_and_the_screen_shows_the_new_candidates(self):
        out = self.ok("candidates", "suggest", "--blog", "naver_a", "--add", "1,2", "--yes")
        self.assertIn("제안 2개를 새 후보(출처: 프로필 제안)로 보관함에 넣었습니다 — 네이버 A", out)
        self.assertEqual(len(re.findall(r"^  \[\d\] 새 후보 — ", out, re.M)), 2)
        self.assertIn("candidates select 순번 --blog naver_a", out)
        self.assertEqual(len(self.stored()), 2)
        self.assertIsNone(LONG_ID.search(out))
        listing = self.ok("candidates", "list")
        self.assertIn("  [1] 새 후보 — ", listing)

    def test_the_same_command_twice_adds_nothing_the_second_time_and_says_so(self):
        self.ok("candidates", "suggest", "--blog", "naver_a", "--add", "1,2", "--yes")
        out = self.ok("candidates", "suggest", "--blog", "naver_a", "--add", "1,2", "--yes")
        self.assertIn("넣은 제안이 없습니다 — 네이버 A", out)
        self.assertNotIn("미리 보기", out, "확인했는데 넣을 것이 없을 때는 미리 보기가 아니다")
        self.assertNotIn("다음:", out, "넣은 것이 없으면 '다음에 할 일' 안내도 없다")
        self.assertIn("건너뜀 번호 1: 이미 보관함에 있거나 최근에 고른 제안이라 숨겨져 있습니다", out)
        self.assertEqual(len(self.stored()), 2)

    def test_add_without_a_blog_uses_the_only_blog_that_has_a_profile(self):
        out = self.ok("candidates", "suggest", "--add", "1", "--yes")
        self.assertIn("제안 1개를 새 후보(출처: 프로필 제안)로 보관함에 넣었습니다 — 네이버 A", out)
        self.assertEqual([item.blogs for item in self.stored()], [("naver_a",)])

    def test_the_hint_repeats_the_options_that_change_the_numbers(self):
        plain = self.ok("candidates", "suggest", "--blog", "naver_a")
        self.assertRegex(plain, r"넣으려면: `python -m chanceblog_desktop candidates suggest --blog naver_a --add 1,2,3 --yes`")
        custom = self.ok("candidates", "suggest", "--blog", "naver_a", "--count", "7", "--month", "12", "--type", "문제 해결")
        self.assertIn("candidates suggest --blog naver_a --count 7 --month 12 --type \"문제 해결형\" --add 1,2,3 --yes`", custom)
        month_now = self.ok("candidates", "suggest", "--blog", "naver_a", "--month", "11", "--type", "비교")
        self.assertIn("candidates suggest --blog naver_a --type 비교형 --add 1,2,3 --yes`", month_now, "오늘의 달과 같은 --month 와 기본 개수는 적지 않는다")
        hint = re.search(r"넣으려면: `python -m chanceblog_desktop (candidates suggest .*? --yes)`", custom).group(1)
        before = self.data("candidates", "suggest", "--blog", "naver_a", "--count", "7", "--month", "12", "--type", "문제 해결형")["blogs"][0]["suggestions"][:3]
        self.ok(*shlex.split(hint, posix=True))
        self.assertEqual([item.keyword for item in self.stored()], [item["keyword"] for item in before], "안내한 명령을 그대로 실행하면 같은 번호가 들어간다")
        self.assertEqual(self.data("candidates", "suggest", "--blog", "naver_a")["blogs"][0]["post_type"], None)
        self.assertEqual(self.data("candidates", "suggest", "--blog", "naver_a", "--type", "비교")["blogs"][0]["post_type"], "비교형")

    def test_a_keyword_beyond_the_requested_count_can_still_be_added_by_its_text(self):
        wide = self.data("candidates", "suggest", "--blog", "naver_a", "--count", "40")["blogs"][0]["suggestions"]
        far = wide[25]["keyword"]
        narrow = {item["keyword"] for item in self.data("candidates", "suggest", "--blog", "naver_a", "--count", "5")["blogs"][0]["suggestions"]}
        self.assertNotIn(far, narrow)
        out = self.ok("candidates", "suggest", "--blog", "naver_a", "--count", "5", "--add", far, "--yes")
        self.assertIn("제안 1개를 새 후보", out)
        self.assertEqual([item.keyword for item in self.stored()], [far])

    def test_a_repeated_add_option_joins_the_values_instead_of_keeping_only_the_last(self):
        preview = self.ok("candidates", "suggest", "--blog", "naver_a", "--count", "6", "--add", "1", "--add", "3,5")
        self.assertEqual([preview.count(f"넣을 제안 [{rank}] ") for rank in (1, 2, 3, 4, 5)], [1, 0, 1, 0, 1], preview)
        self.ok("candidates", "suggest", "--blog", "naver_a", "--count", "6", "--add", "1", "--add", "3,5", "--yes")
        self.assertEqual(len(self.stored()), 3)
        err = self.fails("candidates", "suggest", "--blog", "naver_a", "--add", "all", "--add", "2", code=2)
        self.assertIn("all 은 다른 값과 함께 쓸 수 없습니다", err)

    def test_the_hint_for_the_second_page_names_the_numbers_on_that_screen_and_works(self):
        first = self.ok("candidates", "suggest", "--blog", "naver_a", "--count", "6")
        self.assertIn("이 화면의 제안을 모두 넣으려면 `--add 1-6`(처음 보이던 번호 1~6 전부는 `all` 로도 넣을 수 있습니다)", first)
        self.ok("candidates", "suggest", "--blog", "naver_a", "--count", "6", "--add", "all", "--yes")
        self.assertEqual(len(self.stored()), 6)
        second = self.ok("candidates", "suggest", "--blog", "naver_a", "--count", "6")
        self.assertIn("  [7] ", second)
        self.assertNotIn("  [1] ", second)
        self.assertIn("이 화면의 제안을 모두 넣으려면 `--add 7-12`", second)
        hint = re.search(r"이 화면의 제안을 모두 넣으려면 `(--add [0-9-]+)`", second).group(1)
        self.ok("candidates", "suggest", "--blog", "naver_a", "--count", "6", *hint.split(), "--yes")
        self.assertEqual(len(self.stored()), 12, "화면의 안내대로 넣으면 그 화면의 제안 여섯이 들어간다")
        again = self.ok("candidates", "suggest", "--blog", "naver_a", "--count", "6", "--add", "all", "--yes")
        self.assertIn("넣은 제안이 없습니다", again, "all 은 여전히 처음 보이던 번호 1~개수라 되풀이해도 늘지 않는다")

    def test_the_listed_hint_command_can_be_run_as_printed(self):
        first_keyword = self.data("candidates", "suggest", "--blog", "naver_a", "--count", "4")["blogs"][0]["suggestions"][0]["keyword"]
        out = self.ok("candidates", "suggest", "--blog", "naver_a", "--count", "4")
        hint = re.search(r"넣으려면: `python -m chanceblog_desktop (candidates suggest .*? --yes)`", out).group(1)
        argv = shlex.split(hint, posix=True)
        self.assertEqual(argv[:4], ["candidates", "suggest", "--blog", "naver_a"])
        self.assertEqual(re.search(r"\(예: `--add \"(.+?)\"`\)", out).group(1), first_keyword, "키워드 예시는 맨 위 제안의 키워드다")
        self.ok(*argv, "--count", "4")
        self.assertEqual(len(self.stored()), 3, "안내한 번호(1,2,3)가 들어갔다")

    def test_an_added_suggestion_by_keyword_text_and_by_all(self):
        first = self.data("candidates", "suggest", "--blog", "naver_a", "--count", "3")["blogs"][0]["suggestions"]
        self.ok("candidates", "suggest", "--blog", "naver_a", "--add", first[2]["keyword"], "--yes", "--count", "3")
        self.assertEqual([item.keyword for item in self.stored()], [first[2]["keyword"]])
        self.ok("candidates", "suggest", "--blog", "naver_a", "--add", "all", "--yes", "--count", "3")
        self.assertEqual(sorted(item.keyword for item in self.stored()), sorted(item["keyword"] for item in first))

    def test_a_json_add_result_lists_items_added_and_skipped(self):
        data = self.data("candidates", "suggest", "--blog", "naver_a", "--add", "1,2", "--yes")
        self.assertEqual((data["confirmed"], len(data["added"]), data["late_skips"]), (True, 2, []))
        self.assertEqual(data["added"][0]["ordinal"], 1)
        self.assertRegex(data["added"][0]["candidate_id"], r"^[0-9a-f]{32}$")
        again = self.data("candidates", "suggest", "--blog", "naver_a", "--add", "1,2", "--yes")
        self.assertEqual((again["added"], [item["action"] for item in again["items"]]), ([], ["skip", "skip"]))


class PriorityOutputTest(Base):
    def setUp(self):
        super().setUp()
        self.ok("candidates", "add", "--topic", "겨울 보일러 난방 점검 순서", "--keyword", "보일러 난방 점검", "--blog", "naver_a", "--search-demand", "5000", "--related-results", "40000", "--trend", "상승",
                "--data-date", "2026-09-30", "--priority", "12.5")
        self.ok("candidates", "add", "--topic", "자전거 타기", "--keyword", "자전거", "--blog", "github_pages")

    def test_list_without_the_flag_is_exactly_what_it_was_and_the_json_has_no_new_key(self):
        out = self.ok("candidates", "list")
        self.assertNotIn("우선도", out)
        self.assertEqual(out.count("콘텐츠 작성 우선도"), 0)
        data = self.data("candidates", "list")
        self.assertTrue(all("priority_info" not in item for item in data["candidates"]))
        self.assertEqual(set(data), {"candidates", "total", "shown", "status", "blog", "store"})

    def test_list_with_the_flag_appends_the_calculated_priority_and_the_fit_and_the_data_age(self):
        before = self.state()
        out = self.ok("candidates", "list", "--priority")
        self.assertEqual(self.state(), before, "읽기만 한다 — 보관함 값은 바뀌지 않는다")
        lines = [line for line in out.splitlines() if line.startswith("  [")]
        self.assertRegex(lines[0], r"· 콘텐츠 작성 우선도 (높음|보통) [0-9.]+점\(블로그 프로필 적합도 100\) · 이유: 시기 \d+·신선도 \d+·균형 \d+·키워드 기회도 [0-9.]+ · 조회일 2026-09-30\(33일 전 조회\) — 오래된 데이터\(30일 넘음, 다시 조회해 확인\)$")
        self.assertRegex(lines[1], r"· 콘텐츠 작성 우선도 (높음|보통|낮음) [0-9.]+점\(블로그 프로필 적합도 데이터 없음\) · 이유: 시기 \d+·신선도 \d+·균형 \d+$")
        self.assertIn("우선도는 보관함에 저장된 값이 아니라", out)
        stored = {item.keyword: item for item in self.stored()}
        self.assertEqual(stored["보일러 난방 점검"].priority, 12.5, "저장된 값 12.5 는 그대로다")
        self.assertNotIn("12.5", out, "저장된 값이 계산에 섞이거나 화면에 대신 나오지 않는다")

    def test_list_priority_json_adds_priority_info_per_candidate(self):
        data = self.data("candidates", "list", "--priority")
        first, second = data["candidates"]
        self.assertEqual(set(first["priority_info"]), {"priority", "profile_fit", "season", "data", "similar_post_exists", "reason", "notes", "factors"})
        self.assertEqual(first["priority_info"]["profile_fit"], 100)
        self.assertIsNone(second["priority_info"]["profile_fit"])
        self.assertTrue(first["priority_info"]["data"]["stale"])
        self.assertEqual(first["priority"], 12.5, "저장된 priority 칸은 그대로 있고 계산한 값은 priority_info 에 따로")
        self.assertIn("opportunity", [item["name"] for item in first["priority_info"]["factors"]])
        self.assertNotIn("opportunity", [item["name"] for item in second["priority_info"]["factors"]])

    def test_list_priority_follows_the_filters(self):
        out = self.ok("candidates", "list", "--priority", "--blog", "github_pages")
        self.assertIn("자전거 타기", out)
        self.assertNotIn("보일러 난방 점검", out)
        self.assertIn("블로그 프로필 적합도 데이터 없음", out)
        empty = ss.make_ctx(self.tmp / "다른 곳", repo="")
        code, out, err = ss.run_cli(empty, "candidates", "list", "--priority")
        self.assertEqual((code, err), (0, ""))
        self.assertIn("아직 후보가 없습니다", out)

    def test_show_explains_why_it_has_this_priority_and_keeps_the_stored_values_apart(self):
        out = self.ok("candidates", "show", "1")
        self.assertIn("  계산한 콘텐츠 작성 우선도: ", out)
        self.assertIn("보관함에 저장된 값은 바뀌지 않습니다", out)
        self.assertIn("    왜 이 우선도인지: ", out)
        self.assertIn("키워드 기회도", out)
        self.assertIn("  블로그 프로필 적합도(계산): 100", out)
        self.assertIn("  지표 조회: 조회일 2026-09-30(33일 전 조회) — 오래된 데이터", out)
        self.assertIn("콘텐츠 작성 우선도: 12.5(이전에 적어 둔 값 — 아래 계산값과 따로이고 계산에는 쓰이지 않습니다)", out, "저장된 지표 줄은 그대로 있고 '이전에 적어 둔 값' 이라고 밝힌다")
        data = self.data("candidates", "show", "1")["candidate"]
        self.assertEqual(data["priority_info"]["profile_fit"], 100)
        self.assertEqual(data["priority"], 12.5)
        plain = self.ok("candidates", "show", "2")
        self.assertIn("블로그 프로필 적합도(계산): 데이터 없음", plain)
        self.assertIn("프로필이 없거나 주제가 비어 있어", plain)

    def test_a_broken_settings_file_does_not_break_show_and_is_explained(self):
        self.ctx.workspace.settings_path.write_text("{ 깨진", encoding="utf-8")
        out = self.ok("candidates", "show", "1")
        self.assertIn("SETTINGS_INVALID", out)
        self.assertIn("블로그 프로필 적합도(계산): 데이터 없음", out)


if __name__ == "__main__":
    unittest.main()
