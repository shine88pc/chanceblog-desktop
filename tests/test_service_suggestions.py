"""자동 후보 제안 서비스(`service/suggestions.py`) 시험 — 읽기 전용·기존 글 읽기·`--add` 멱등·보관함 후보의 우선도.

지키는 것:
  1) `suggest` 는 **읽기만 한다** — 실행 전후 데이터 폴더의 모든 파일이 바이트·수정 시각까지 같고(보관함 파일이 없으면 만들지도 않고, 옛 구조(판 1)도 올리지 않는다), 후보가 하나도 없어도 프로필로 제안한다.
  2) 기존 글 제목은 보관함의 원고 제목과 '선택됨' 후보의 주제에서 읽는다(고르지 않은 후보의 주제는 기존 글이 아니다). 같은 키워드(같은 블로그)가 보관함에 있으면 숨긴다.
  3) `--add` 는 `--yes` 없이는 아무것도 넣지 않고, 넣을 때 **키워드(같은 블로그)로 다시 확인해** 같은 명령을 되풀이해도·그 사이 다른 명령이 넣어도 겹치지 않는다. 번호는 같은 입력이면 같은 번호이고 넣은 제안은 숨겨지되 번호가 그대로라 다른 제안이 들어오지 않는다.
  4) 없는 번호·키워드는 `SUGGESTION_NOT_FOUND` 로 아무것도 넣지 않고 멈추며 오류 문구에 사용자가 친 값을 싣지 않는다.
  5) 후보 우선도(`assess_rows`)는 보관함 값을 바꾸지 않고, 설정 파일이 깨졌으면 그 사실을 알리고 적합도 없이 계산한다.
"""
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import service_support as ss  # noqa: E402
import suggest_support as sp  # noqa: E402
from store_v1 import make_v1_file  # noqa: E402

from chanceblog_desktop.content import candidates as cd  # noqa: E402
from chanceblog_desktop.content import suggest as sg  # noqa: E402
from chanceblog_desktop.content.model import ContentProject  # noqa: E402
from chanceblog_desktop.content.store import Store  # noqa: E402
from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.service import candidates as cands  # noqa: E402
from chanceblog_desktop.service import projects  # noqa: E402
from chanceblog_desktop.service import suggestions as svc  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.ctx = ss.make_ctx(self.tmp, repo="")
        self.root = self.ctx.workspace.root
        self.store_path = self.ctx.workspace.store_path

    def save(self, prof):
        self.ctx.settings.save_naver_profile(prof)

    def folder_state(self):
        """데이터 폴더의 모든 파일 → (바이트, 수정 시각) — 앞뒤 비교로 '아무것도 쓰지 않았다' 를 본다."""
        if not self.root.exists():
            return None
        return {path.relative_to(self.root).as_posix(): (path.read_bytes(), path.stat().st_mtime_ns) for path in sorted(self.root.rglob("*")) if path.is_file()}

    def stored(self):
        with Store.open(self.store_path, migrate=False) as store:
            return store.list_candidates()

    def code(self, call, *args, **kwargs):
        return ss.code_of(call, *args, **kwargs)


class ReadOnlyTest(Base):
    def test_without_any_data_folder_the_profile_guidance_comes_and_nothing_is_created(self):
        result = svc.run_suggest(self.ctx)
        self.assertEqual([(group.blog, group.report.guidance) for group in result.groups], [("naver_a", sg.GUIDANCE)])
        self.assertEqual(result.vault_state, "missing")
        self.assertFalse(self.root.exists(), "읽기만 하는 명령은 데이터 폴더도 만들지 않는다")

    def test_a_profile_alone_is_enough_and_no_vault_file_is_made(self):
        self.save(sp.rich())
        before = self.folder_state()
        result = svc.run_suggest(self.ctx)
        self.assertEqual(len(result.groups[0].report.suggestions), 10)
        self.assertEqual(self.folder_state(), before)
        self.assertFalse(self.store_path.exists())

    def test_an_existing_vault_is_left_byte_for_byte_and_mtime_for_mtime_the_same(self):
        self.save(sp.rich())
        cands.add_candidate(self.ctx, topic="보관함 후보", keyword="보관함 키워드", blogs=("naver_a",))
        projects.new_project(self.ctx, "보관함의 글", ss.ko_text())
        before = self.folder_state()
        self.assertIn("chanceblog.db", before)
        svc.run_suggest(self.ctx)
        svc.run_suggest(self.ctx, blog="naver_a", count=3, month=7, post_type="비교형")
        rows = cands.list_candidates(self.ctx).rows
        svc.assess_rows(self.ctx, rows)
        svc.add_suggestions(self.ctx, svc.parse_add_spec("1,2"), blog="naver_a")                # 미리 보기도 읽기만 한다
        self.assertEqual(self.folder_state(), before)

    def test_an_old_structure_vault_is_not_raised_and_still_gives_suggestions(self):
        self.save(sp.rich())
        self.root.mkdir(parents=True, exist_ok=True)
        make_v1_file(self.store_path, projects=[ContentProject.new("옛 글 제목", "본문입니다.", project_id="p1", now="2026-11-02T00:00:00Z")])
        before = self.folder_state()
        result = svc.run_suggest(self.ctx)
        self.assertEqual(result.vault_state, "old_structure")
        self.assertTrue(result.groups[0].report.suggestions)
        self.assertEqual(self.folder_state(), before, "판 1 파일을 올리지도 사본(.v1.bak)을 만들지도 않는다")

    def test_a_vault_with_an_unfinished_save_stops_with_the_recovery_code_instead_of_touching_it(self):
        self.save(sp.rich())
        cands.add_candidate(self.ctx, topic="후보", keyword="키워드", blogs=("naver_a",))
        journal = Path(str(self.store_path) + "-journal")
        journal.write_bytes(b"" * 16)                                          # 쓰다 죽어서 남은 저널(내용이 있다)
        before = self.folder_state()
        with mock.patch.object(Store, "_verify", side_effect=sqlite3.OperationalError("attempt to write a readonly database")):
            self.assertEqual(self.code(svc.run_suggest, self.ctx).code, "STORE_RECOVERY_PENDING")
            self.assertEqual(self.code(svc.assess_rows, self.ctx, []).code, "STORE_RECOVERY_PENDING")
        self.assertEqual(self.folder_state(), before, "멈추면서 아무것도 바꾸지 않았다")


class InputsTest(Base):
    def test_the_blogs_asked_for_are_the_profiled_naver_blogs_or_the_one_named(self):
        self.save(sp.rich())
        self.assertEqual([group.blog for group in svc.run_suggest(self.ctx).groups], ["naver_a"])
        self.save(sp.rich("naver_b", topic="여행 계획, 맛집"))
        result = svc.run_suggest(self.ctx)
        self.assertEqual([(group.blog, group.profile_name) for group in result.groups], [("naver_a", "블로그 에이"), ("naver_b", "블로그 비")])
        self.assertEqual([group.blog for group in svc.run_suggest(self.ctx, blog="naver_b").groups], ["naver_b"])
        self.assertEqual(svc.profiled_blogs(self.ctx), ("naver_a", "naver_b"))

    def test_a_blog_without_a_saved_profile_gets_the_profile_guidance_and_a_non_naver_blog_gets_its_own_note(self):
        self.save(sp.rich())
        missing = svc.run_suggest(self.ctx, blog="naver_b").groups[0]
        self.assertEqual((missing.report.guidance, missing.report.suggestions, missing.profile_name), (sg.GUIDANCE, (), ""))
        other = svc.run_suggest(self.ctx, blog="github_pages").groups[0]
        self.assertEqual(other.report.guidance, svc.OTHER_BLOG_GUIDANCE)
        self.assertIn("네이버 A·B 프로필", svc.OTHER_BLOG_GUIDANCE)
        self.assertEqual(other.report.suggestions, ())

    def test_each_blog_uses_its_own_profile_and_its_own_vault_keywords(self):
        self.save(sp.profile(topic="보일러 난방"))
        self.save(sp.profile("naver_b", topic="여행 계획"))
        result = svc.run_suggest(self.ctx)
        seeds = {group.blog: [seed.text for seed in group.report.seeds] for group in result.groups}
        self.assertEqual(seeds, {"naver_a": ["보일러 난방"], "naver_b": ["여행 계획"]})
        cands.add_candidate(self.ctx, topic="이미 있는 후보", keyword="보일러 난방", blogs=("naver_a",))
        after = svc.run_suggest(self.ctx, blog="naver_a").groups[0].report
        self.assertNotIn("보일러 난방", [item.keyword for item in after.suggestions])
        self.assertTrue(any(code == sg.VAULT for code, _label, _number, _hidden in after.filtered))
        self.assertEqual([code for code, *_ in svc.run_suggest(self.ctx, blog="naver_b").groups[0].report.filtered], [], "다른 블로그의 키워드는 다른 블로그 제안을 숨기지 않는다")

    def test_the_existing_titles_are_the_project_titles_and_the_selected_candidates_topics_only(self):
        self.save(sp.profile(topic="자전거, 보일러 난방"))
        wanted = [seed for seed in ("자전거 처음 알아볼 때 꼭 짚어 둘 기본 정리", "보일러 난방 처음 알아볼 때 꼭 짚어 둘 기본 정리")]
        projects.new_project(self.ctx, wanted[0], ss.ko_text())
        cands.add_candidate(self.ctx, topic=wanted[1], keyword="완전히 다른 키워드", blogs=("naver_a",))              # 고르지 않은 후보 — 기존 글이 아니다
        vault = svc.read_vault(self.ctx)
        self.assertEqual(vault.titles(), (wanted[0],))
        report = svc.run_suggest(self.ctx).groups[0].report
        self.assertEqual({code: number for code, _label, number, _hidden in report.filtered}.get(sg.SIMILAR), 1, "원고 제목과 같은 제안 하나만 비슷한 글로 걸린다")
        self.ctx.clock.advance(seconds=5)
        cands.select_candidate(self.ctx, "1", "naver_a")
        self.assertEqual(svc.read_vault(self.ctx).titles(), (wanted[0], wanted[1]), "고른 후보의 주제는 쓰기로 한 글이라 기존 글로 본다")
        after = svc.run_suggest(self.ctx).groups[0].report
        self.assertEqual({code: number for code, _label, number, _hidden in after.filtered}.get(sg.SIMILAR), 2)
        self.assertEqual(sp.independent_problems(after, sp.profile(topic="자전거, 보일러 난방")), [])

    def test_a_recent_selection_hides_the_keyword_for_that_blog_by_the_korean_calendar(self):
        self.save(sp.profile(topic="보일러 난방", topic_reuse_days=30))
        cands.add_candidate(self.ctx, topic="글감", keyword="보일러 난방", blogs=("naver_a", "naver_b"))
        cands.select_candidate(self.ctx, "1", "naver_a")
        report = svc.run_suggest(self.ctx).groups[0].report
        self.assertNotIn("보일러 난방", [item.keyword for item in report.suggestions])
        self.assertEqual([(code, hidden) for code, _label, _number, hidden in report.filtered if code in (sg.RECENT, sg.VAULT)], [(sg.RECENT, True)], "최근 선택이 먼저 센다")
        self.ctx.clock.advance(days=31)
        later = svc.run_suggest(self.ctx).groups[0].report
        self.assertEqual([(code, hidden) for code, _label, _number, hidden in later.filtered if code in (sg.RECENT, sg.VAULT)], [(sg.VAULT, True)], "31일이 지나면 최근이 아니고 보관함에 있는 것으로만 숨긴다")

    def test_the_month_and_the_day_come_from_the_context_clock_in_korean_time(self):
        self.save(sp.rich())
        self.assertEqual(svc.today_of(self.ctx).isoformat(), "2026-11-02")
        self.ctx.clock.advance(hours=14)                                                  # UTC 15:30 → 한국 시간 다음 날 00:30
        self.assertEqual(svc.today_of(self.ctx).isoformat(), "2026-11-03")
        self.assertEqual(svc.run_suggest(self.ctx).groups[0].report.today, "2026-11-03")
        self.ctx.clock.advance(days=30)
        self.assertEqual(svc.run_suggest(self.ctx).groups[0].report.month, 12)

    def test_a_broken_settings_file_is_reported_not_hidden(self):
        self.root.mkdir(parents=True, exist_ok=True)
        self.ctx.workspace.settings_path.write_text("{ 깨진 파일", encoding="utf-8")
        self.assertEqual(self.code(svc.run_suggest, self.ctx).code, "SETTINGS_INVALID")


class MergeAddSpecsTest(unittest.TestCase):
    def test_values_are_joined_in_order_without_repeats(self):
        self.assertEqual(svc.merge_add_specs([(1,), (3, 5), (1, "난방 점검")]), (1, 3, 5, "난방 점검"))
        self.assertEqual(svc.merge_add_specs([("all",), ("all",)]), ("all",))

    def test_all_cannot_be_mixed_and_the_size_is_capped(self):
        for parts in ([("all",), (2,)], [(2,), ("all",)]):
            with self.assertRaises(ValueError):
                svc.merge_add_specs(parts)
        with self.assertRaises(ValueError):
            svc.merge_add_specs([tuple(range(1, 150)), tuple(range(150, 260))])


class ParseSpecTest(unittest.TestCase):
    def test_numbers_ranges_all_and_keywords(self):
        self.assertEqual(svc.parse_add_spec("3"), (3,))
        self.assertEqual(svc.parse_add_spec("1,3，5"), (1, 3, 5))
        self.assertEqual(svc.parse_add_spec(" 2 - 4 , 9"), (2, 3, 4, 9))
        self.assertEqual(svc.parse_add_spec("1,1,2,2-3"), (1, 2, 3), "겹치는 것은 처음 하나만")
        self.assertEqual(svc.parse_add_spec("ALL"), ("all",))
        self.assertEqual(svc.parse_add_spec("전체"), ("all",))
        self.assertEqual(svc.parse_add_spec("보일러 난방,2"), ("보일러 난방", 2))
        self.assertEqual(svc.parse_add_spec("007"), (7,))

    def test_bad_values_are_refused_without_echoing_what_was_typed(self):
        secret = ss.KEY
        for bad, why in (("", "적어야"), (" , ，", "적어야"), ("all,1", "all 은"), ("0", "1 이상"), ("5-2", "범위"), ("0-3", "범위"), ("1-999", "범위"), ("1-201", "범위"), ("x" * 3000, "너무 깁니다"),
                         (",".join(str(number) for number in range(1, 300)), "까지 넣을 수")):
            with self.assertRaises(ValueError) as caught:
                svc.parse_add_spec(bad)
            self.assertIn(why, str(caught.exception), bad[:20])
        with self.assertRaises(ValueError) as caught:
            svc.parse_add_spec(secret + ",0")
        self.assertNotIn(secret, str(caught.exception))
        with self.assertRaises(ValueError):
            svc.parse_add_spec(None)

    def test_the_largest_accepted_number_and_range_edges(self):
        self.assertEqual(svc.parse_add_spec("999999"), (999999,))
        self.assertEqual(svc.parse_add_spec("1-200")[-1], 200)
        self.assertEqual(len(svc.parse_add_spec(",".join(str(number) for number in range(1, 201)))), 200)


class AddTest(Base):
    def setUp(self):
        super().setUp()
        self.save(sp.rich())

    def add(self, spec, **kwargs):
        kwargs.setdefault("blog", "naver_a")
        return svc.add_suggestions(self.ctx, svc.parse_add_spec(spec), **kwargs)

    def suggestions(self, **kwargs):
        return svc.run_suggest(self.ctx, blog="naver_a", **kwargs).groups[0].report

    def test_without_yes_nothing_is_added_and_the_list_to_add_is_shown(self):
        before = self.folder_state()
        result = self.add("1,2")
        self.assertEqual((result.confirmed, result.added, result.late_skips), (False, (), ()))
        self.assertEqual([item.suggestion.rank for item in result.items], [1, 2])
        self.assertEqual([item.action for item in result.items], ["add", "add"])
        self.assertEqual(self.folder_state(), before)
        self.assertFalse(self.store_path.exists())
        for flag in (None, False, 1, "yes", "true"):
            self.assertFalse(self.add("1", confirmed=flag).confirmed, f"confirmed={flag!r} 은 확인이 아니다")
        self.assertFalse(self.store_path.exists())

    def test_with_yes_the_chosen_suggestions_become_new_candidates_with_the_profile_source_mark(self):
        first = self.suggestions()
        result = self.add("1,3,2", confirmed=True)
        self.assertTrue(result.confirmed)
        self.assertEqual([row.candidate.keyword for row in result.added], [first.suggestions[0].keyword, first.suggestions[2].keyword, first.suggestions[1].keyword])
        stored = {item.keyword: item for item in self.stored()}
        self.assertEqual(len(stored), 3)
        for source in (first.suggestions[0], first.suggestions[1], first.suggestions[2]):
            item = stored[source.keyword]
            self.assertEqual((item.topic, item.sub_keywords, item.blogs, item.post_type, item.status, item.project_id), (source.topic, source.sub_keywords, ("naver_a",), source.post_type, cd.NEW, None))
            self.assertEqual(item.reason, source.stored_reason)
            self.assertTrue(item.reason.startswith("프로필 제안 — "))
            self.assertEqual((item.search_demand, item.related_blog_results, item.trend, item.data_date, item.priority, item.profile_fit, item.keyword_opportunity), (None,) * 7,
                             "계산한 점수·적합도를 보관함에 저장하지 않는다(스키마도 지표 칸도 쓰지 않는다)")
            self.assertEqual(item.revision, 1)
        self.assertEqual(self.stored()[0].created_at, self.ctx.stamp())

    def test_the_new_candidates_get_ordinals_in_the_order_the_suggestions_were_chosen(self):
        cands.add_candidate(self.ctx, topic="먼저 있던 후보", keyword="먼저 있던 키워드", blogs=("naver_a",))
        result = self.add("3,1,2", confirmed=True)
        self.assertEqual([row.ordinal for row in result.added], [2, 3, 4])
        listing = cands.list_candidates(self.ctx).rows
        self.assertEqual([row.candidate.keyword for row in listing][1:], [row.candidate.keyword for row in result.added])
        self.assertEqual(listing[0].candidate.topic, "먼저 있던 후보", "이미 있던 후보의 순번은 바뀌지 않는다")

    def test_running_the_same_add_again_adds_nothing_and_never_pulls_in_other_suggestions(self):
        original = self.suggestions().suggestions
        first = self.add("1,2", confirmed=True)
        self.assertEqual(len(first.added), 2)
        again = self.add("1,2", confirmed=True)
        self.assertEqual((again.confirmed, again.added, len(again.items)), (True, (), 2))
        self.assertEqual([item.action for item in again.items], ["skip", "skip"])
        self.assertTrue(all("이미 보관함에 있거나 최근에 고른" in item.reason for item in again.items))
        self.assertEqual(len(self.stored()), 2, "같은 번호를 되풀이해도 후보는 둘뿐이다")
        third = self.add("1,2,3", confirmed=True)
        self.assertEqual(len(third.added), 1, "번호 3 만 새로 들어간다")
        self.assertEqual(len(self.stored()), 3)
        self.assertEqual(third.added[0].candidate.keyword, original[2].keyword, "번호 3 은 처음 보던 3번 제안이다")

    def test_a_keyword_is_found_by_text_and_a_second_time_it_is_skipped_not_an_error(self):
        wanted = self.suggestions().suggestions[3]
        preview = svc.add_suggestions(self.ctx, svc.parse_add_spec(wanted.keyword), blog="naver_a")
        self.assertEqual((preview.items[0].suggestion.rank, preview.items[0].label), (4, "키워드"), "목록에 있는 키워드는 번호가 있는 그 제안으로 찾는다")
        first = svc.add_suggestions(self.ctx, svc.parse_add_spec(wanted.keyword), blog="naver_a", confirmed=True)
        self.assertEqual([row.candidate.keyword for row in first.added], [wanted.keyword])
        again = svc.add_suggestions(self.ctx, svc.parse_add_spec(wanted.keyword), blog="naver_a", confirmed=True)
        self.assertEqual((again.added, [item.action for item in again.items], again.items[0].reason), ((), ["skip"], "이미 보관함에 있습니다"))
        spaced = svc.add_suggestions(self.ctx, svc.parse_add_spec(wanted.keyword.replace(" ", "-")), blog="naver_a", confirmed=True)
        self.assertEqual(spaced.items[0].action, "skip", "띄어쓰기·기호가 달라도 같은 키워드")
        self.assertEqual(len(self.stored()), 1)

    def test_a_vault_keyword_outside_the_list_is_skipped_by_text_too_not_added_twice(self):
        far = self.suggestions(count=40).suggestions[25].keyword
        self.assertNotIn(far, [item.keyword for item in self.suggestions(count=5).suggestions])
        cands.add_candidate(self.ctx, topic="이미 있는 글감", keyword=far, blogs=("naver_a",))
        result = svc.add_suggestions(self.ctx, svc.parse_add_spec(far), blog="naver_a", count=5, confirmed=True)
        self.assertEqual([(item.action, item.reason) for item in result.items], [("skip", "이미 보관함에 있습니다")])
        self.assertEqual((result.added, result.late_skips, len(self.stored())), ((), (), 1))

    def test_a_keyword_still_finds_its_suggestion_after_the_numbers_have_moved(self):
        before = self.suggestions().suggestions
        target = before[5]
        for item in before[:2]:                                                     # 그 사이 다른 명령이 앞의 제안 둘을 넣었다 — 번호는 그대로이지만 다른 이유로 목록이 달라질 수 있다
            cands.add_candidate(self.ctx, topic=item.topic, keyword=item.keyword, blogs=("naver_a",))
        result = svc.add_suggestions(self.ctx, svc.parse_add_spec(target.keyword), blog="naver_a", confirmed=True)
        self.assertEqual([row.candidate.keyword for row in result.added], [target.keyword])

    def test_all_adds_the_numbers_one_to_count_once_and_a_repeat_adds_nothing(self):
        shown = self.suggestions(count=7).suggestions
        result = self.add("all", count=7, confirmed=True)
        self.assertEqual([row.candidate.keyword for row in result.added], [item.keyword for item in shown])
        again = self.add("all", count=7, confirmed=True)
        self.assertEqual((again.added, len(self.stored())), ((), 7), "같은 all 을 되풀이해도 다음 제안이 딸려 들어가지 않는다")
        self.assertEqual([(item.label, item.action) for item in again.items], [("all", "skip")])
        self.assertIn("번호 1, 2, 3, 4, 5, 6, 7 ", again.items[0].reason)
        self.assertEqual(len({cd.keyword_key(item.keyword) for item in self.stored()}), 7)
        page_two = self.add("8-10", count=7, confirmed=True)
        self.assertEqual(len(page_two.added), 3, "다음 쪽은 번호 범위로 넣는다")

    def test_all_follows_the_requested_count_and_skips_only_the_hidden_numbers_inside_the_window(self):
        self.add("2", confirmed=True)
        result = self.add("all", count=5, confirmed=True)
        self.assertEqual(len(result.added), 4, "1~5 중 번호 2 는 이미 넣었다")
        self.assertEqual([item.reason for item in result.items if item.action == "skip"], ["번호 2 은(는) 이미 보관함에 있거나 최근에 고른 제안이라 숨겨져 있습니다(번호는 그대로입니다)"])
        self.assertEqual(len(self.stored()), 5)

    def test_the_same_suggestion_named_by_number_and_by_keyword_is_added_once(self):
        wanted = self.suggestions().suggestions[0]
        result = svc.add_suggestions(self.ctx, (1, wanted.keyword, "all"), blog="naver_a", confirmed=True)
        self.assertEqual(len([item for item in result.items if item.suggestion is not None and item.suggestion.rank == 1]), 1)
        self.assertEqual(len(self.stored()), len({cd.keyword_key(item.keyword) for item in self.stored()}))
        self.assertEqual(len(self.stored()), 10)

    def test_all_with_a_window_wider_than_the_supply_adds_what_exists_and_does_not_invent_the_rest(self):
        self.save(sp.profile(topic="난방"))
        supply = self.suggestions(count=50).suggestions
        self.assertLess(len(supply), 50)
        result = self.add("all", count=50, confirmed=True)
        self.assertEqual(len(result.added), len(supply))
        self.assertEqual(len(self.add("all", count=50, confirmed=True).added), 0)

    def test_a_range_adds_those_numbers(self):
        shown = self.suggestions().suggestions
        result = self.add("2-4", confirmed=True)
        self.assertEqual([row.candidate.keyword for row in result.added], [item.keyword for item in shown[1:4]])

    def test_a_number_or_keyword_that_is_not_in_the_list_stops_everything_before_anything_is_written(self):
        self.add("1", confirmed=True)
        before = self.folder_state()
        for spec, position in (("2,99", 2), ("1000", 1), ("2,없는 키워드", 2), ("zzz", 1)):
            error = self.code(self.add, spec, confirmed=True)
            self.assertEqual(error.code, "SUGGESTION_NOT_FOUND", spec)
            self.assertEqual(error.slots["항목"], f"--add 의 {position}번째 값")
            self.assertEqual(self.folder_state(), before, f"{spec}: 하나라도 없으면 아무것도 넣지 않는다")
        self.assertEqual(self.code(self.add, "2,99").code, "SUGGESTION_NOT_FOUND", "미리 보기에서도 없는 번호는 알린다")

    def test_the_error_does_not_carry_what_the_user_typed(self):
        secret = ss.KEY
        error = self.code(svc.add_suggestions, self.ctx, (secret,), blog="naver_a", confirmed=True)
        self.assertEqual(error.code, "SUGGESTION_NOT_FOUND")
        for text in (error.rendered().message, str(error.detail), error.log_line()):
            self.assertNotIn(secret, text)
            self.assertNotIn("AIza", text)

    def test_a_blog_without_a_profile_has_nothing_to_add_so_any_number_is_not_found(self):
        error = self.code(self.add, "1", blog="naver_b", confirmed=True)
        self.assertEqual(error.code, "SUGGESTION_NOT_FOUND")
        self.assertFalse(self.store_path.exists())

    def test_the_error_for_a_blog_that_cannot_suggest_says_why(self):
        for blog, why in (("naver_b", "주제를 적어 주세요"), ("github_pages", "프로필(주제·카테고리)을 저장해 두는 곳이 아직 없어")):
            error = self.code(self.add, "1", blog=blog, confirmed=True)
            self.assertEqual(error.code, "SUGGESTION_NOT_FOUND", blog)
            self.assertIn("지금 이 블로그에는 제안이 하나도 없다", str(error.detail), blog)
            self.assertIn(why, str(error.detail), blog)
        self.assertNotIn("제안이 하나도 없다", str(self.code(self.add, "99", confirmed=True).detail), "제안이 있는 블로그의 없는 번호는 이유를 덧붙이지 않는다")

    def test_the_post_type_and_month_flags_are_part_of_the_numbering(self):
        compare = self.suggestions(post_type="비교형")
        result = self.add("1", post_type="비교형", confirmed=True)
        self.assertEqual(result.added[0].candidate.keyword, compare.suggestions[0].keyword)
        self.assertEqual(result.added[0].candidate.post_type, "비교형")
        july = svc.add_suggestions(self.ctx, svc.parse_add_spec("1"), blog="naver_a", month=7, confirmed=True)
        self.assertEqual(len(july.added) + sum(item.action == "skip" for item in july.items), 1)

    def test_a_hidden_number_is_skipped_with_the_reason_and_the_others_are_added(self):
        self.add("1,2", confirmed=True)
        result = self.add("1,5", confirmed=True)
        self.assertEqual([(item.label, item.action) for item in result.items], [("번호 1", "skip"), ("번호 5", "add")])
        self.assertEqual(len(result.added), 1)

    def test_a_command_that_ran_in_between_is_caught_inside_the_write_transaction_by_keyword(self):
        first = self.suggestions().suggestions[:2]
        stale = svc.Vault((), (), "ready")                                             # 첫 읽기가 본 보관함 — 그 뒤에 다른 명령이 둘 중 하나를 넣었다
        cands.add_candidate(self.ctx, topic="끼어든 후보", keyword=first[0].keyword, blogs=("naver_a",))
        with mock.patch.object(svc, "read_vault", return_value=stale):
            result = self.add("1,2", confirmed=True)
        self.assertEqual([row.candidate.keyword for row in result.added], [first[1].keyword])
        self.assertEqual(len(result.late_skips), 1)
        self.assertEqual((result.late_skips[0].action, result.late_skips[0].suggestion.keyword), ("skip", first[0].keyword))
        self.assertEqual(sorted(item.keyword for item in self.stored()), sorted([first[0].keyword, first[1].keyword]))
        self.assertEqual(len(self.stored()), 2)

    def test_another_blogs_candidate_with_the_same_keyword_does_not_block_this_blog(self):
        wanted = self.suggestions().suggestions[0]
        cands.add_candidate(self.ctx, topic="다른 블로그용", keyword=wanted.keyword, blogs=("naver_b",))
        result = self.add("1", confirmed=True)
        self.assertEqual([row.candidate.keyword for row in result.added], [wanted.keyword])
        self.assertEqual(len(self.stored()), 2)

    def test_the_added_candidates_validate_as_stored_and_carry_no_experience_wording(self):
        self.add("all", count=20, confirmed=True)
        for item in self.stored():
            cd.Candidate.from_dict(item.to_dict())
            self.assertIsNone(cd.forbidden_claim(item.reason))
        self.assertEqual({item.blogs for item in self.stored()}, {("naver_a",)})

    def test_a_failure_while_writing_leaves_nothing_behind(self):
        self.add("1", confirmed=True)
        before = [item.to_dict() for item in self.stored()]
        with mock.patch.object(Store, "_put_candidate", side_effect=AppError("DISK_FULL")):
            error = self.code(self.add, "2,3", confirmed=True)
        self.assertEqual(error.code, "DISK_FULL")
        self.assertEqual([item.to_dict() for item in self.stored()], before)

    def test_the_add_after_the_suggestion_text_lines_up_with_the_cli_hint(self):
        report = self.suggestions()
        self.assertEqual([item.rank for item in report.suggestions[:3]], [1, 2, 3])


class PriorityTest(Base):
    def setUp(self):
        super().setUp()
        self.save(sp.rich())

    def rows(self):
        return cands.list_candidates(self.ctx).rows

    def test_every_row_gets_an_assessment_and_the_stored_values_are_untouched(self):
        cands.add_candidate(self.ctx, topic="겨울 보일러 난방 점검 순서", keyword="보일러 난방 점검", blogs=("naver_a",), priority=12.5, data_date="2026-11-01")
        cands.add_candidate(self.ctx, topic="자전거 타기", keyword="자전거", blogs=("github_pages",))
        before = self.folder_state()
        found, notes = svc.assess_rows(self.ctx, self.rows())
        self.assertEqual(notes, ())
        ids = [row.candidate.candidate_id for row in self.rows()]
        self.assertEqual(sorted(found), sorted(ids))
        first, second = (found[row.candidate.candidate_id] for row in self.rows())
        self.assertEqual(first.fit, 100)
        self.assertIsNone(second.fit, "프로필을 저장하는 곳이 없는 블로그만 추천 대상이면 적합도는 데이터 없음")
        self.assertEqual(self.folder_state(), before)
        self.assertEqual(self.rows()[0].candidate.priority, 12.5)

    def test_the_first_blog_with_a_profile_is_used_and_the_blog_filter_picks_the_blog(self):
        self.save(sp.profile("naver_b", topic="자전거"))
        cands.add_candidate(self.ctx, topic="자전거 타기", keyword="자전거", blogs=("naver_a", "naver_b"))
        row = self.rows()[0]
        self.assertEqual(svc.assess_rows(self.ctx, [row])[0][row.candidate.candidate_id].fit, 0, "A 프로필(보일러·절약 …)에는 맞지 않는다")
        self.assertEqual(svc.assess_rows(self.ctx, [row], blog="naver_b")[0][row.candidate.candidate_id].fit, 100)

    def test_the_profile_of_a_blog_is_read_once_for_all_its_candidates(self):
        for number in range(3):
            cands.add_candidate(self.ctx, topic=f"주제 {number}", keyword=f"키워드{number}", blogs=("naver_a",))
        with mock.patch.object(svc, "profile_for", wraps=svc.profile_for) as spy:
            found, notes = svc.assess_rows(self.ctx, self.rows())
        self.assertEqual((len(found), notes, spy.call_count), (3, (), 1))

    def test_a_linked_projects_title_is_not_counted_as_another_post(self):
        project = projects.new_project(self.ctx, "겨울 보일러 난방 점검 순서 정리", ss.ko_text())
        cands.add_candidate(self.ctx, topic="점검 주제", keyword="보일러 난방 점검", blogs=("naver_a",))
        row = self.rows()[0]
        self.assertTrue(svc.assess_rows(self.ctx, [row])[0][row.candidate.candidate_id].similar, "이어지지 않았으면 기존 글과 비슷하다")
        cands.link_candidate(self.ctx, "1", project.project_id)
        row = self.rows()[0]
        self.assertFalse(svc.assess_rows(self.ctx, [row])[0][row.candidate.candidate_id].similar, "이어진 글은 자기 자신이다")

    def test_a_broken_settings_file_gives_a_visible_note_and_no_fit_instead_of_failing(self):
        cands.add_candidate(self.ctx, topic="보일러 난방", keyword="보일러 난방", blogs=("naver_a",))
        self.ctx.workspace.settings_path.write_text("{ 깨진", encoding="utf-8")
        found, notes = svc.assess_rows(self.ctx, self.rows())
        self.assertEqual(len(notes), 1)
        self.assertIn("SETTINGS_INVALID", notes[0])
        self.assertIsNone(next(iter(found.values())).fit)

    def test_other_errors_while_reading_the_profile_are_not_swallowed(self):
        cands.add_candidate(self.ctx, topic="보일러 난방", keyword="보일러 난방", blogs=("naver_a",))
        with mock.patch.object(svc, "profile_for", side_effect=AppError("FILE_WRITE_FAILED")):
            self.assertEqual(self.code(svc.assess_rows, self.ctx, self.rows()).code, "FILE_WRITE_FAILED")

    def test_a_missing_vault_gives_nothing_to_assess(self):
        self.assertEqual(svc.assess_rows(self.ctx, []), ({}, ()))
        self.assertFalse(self.store_path.exists())


if __name__ == "__main__":
    unittest.main()
