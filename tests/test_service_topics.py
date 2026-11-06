"""주제 엔진 서비스(`service/topics.py`) 시험 — 남은 자리 연결·읽기 전용 약속·한 트랜잭션 저장·블로그 이력 읽기·Trend 연결·안내 변환·입력 검사·백업(P3, D-59~D-64). 네트워크·실제 시계 없이 돈다.

지키는 것:
  1) `plan`(미리 보기)·`status`·`check`·`top`·`list`·`show`·`review` 는 **아무것도 쓰지 않는다**(보관함 파일도 폴더도 만들지 않고 바이트도 안 바뀐다). `generate` 는 `--yes`(confirmed)가 있을 때만 저장한다.
  2) 저장은 '읽고 판단하고 쓰기' 한 트랜잭션이다 — 중간에 실패하면 하나도 저장되지 않고(발행 이력 장부 포함), 두 곳에서 동시에 해도 겹치지 않는다. 남은 자리는 채널마다 `slots.count_slots` 가 세어 `target=남은 자리` 로 `generate` 를 부른다.
  3) 블로그 파일은 읽기만 하고 못 읽는 것은 건너뛰며 안내한다. 관심도 공급자는 트랜잭션 밖에서 부르고 어떤 실패에도 엔진은 멈추지 않는다.
  4) 사용자 입력(기준일·목표 개수·채널)은 먼저 검사해 CONTENT_INVALID 로 바꾸고 입력한 값은 되풀이하지 않는다. 화면 글에는 파이썬 목록 꼴·내부 코드·`AppError.detail` 이 없다.
"""
import dataclasses
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import service_support as ss  # noqa: E402
import topics_support as ts  # noqa: E402

from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.service import projects, review  # noqa: E402
from chanceblog_desktop.service import topic_files as tf  # noqa: E402
from chanceblog_desktop.service import topics as tp  # noqa: E402
from chanceblog_desktop.topicdb.store import TopicStore, open_for_write, open_read_only  # noqa: E402
from chanceblog_desktop.topics import history as hs  # noqa: E402
from chanceblog_desktop.topics import layout, notice, schedule, seeds, slots, trend  # noqa: E402
from chanceblog_desktop.topics.link import CandidateLink  # noqa: E402

TODAY = "2026-11-10"
KEY_LIKE = "AI" + "za" + "D" * 35


def code_of(call, *args, **kwargs):
    try:
        call(*args, **kwargs)
    except AppError as error:
        return error.code
    return None


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def tree(root):
    return sorted((str(path.relative_to(root)), path.stat().st_size if path.is_file() else -1) for path in Path(root).rglob("*"))


def put(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


class World:
    """임시 폴더의 사용자 데이터 폴더(씨앗·캘린더 포함)와 가짜 블로그 저장소."""

    def __init__(self, tmp, *, with_world=True, repo="chanceblog"):
        self.tmp = Path(tmp)
        self.ctx = ss.make_ctx(tmp, repo=repo)
        self.paths = tf.topic_paths(self.ctx.workspace)
        self.repo = Path(tmp) / repo if repo else None
        if with_world:
            self.write_world()

    def write_world(self):
        pool = [ts.example_seed(seed_id="g1"), ts.example_seed(seed_id="g2", keyword="예시 공기청정기"), ts.example_seed(seed_id="z1", keyword="예시 난방", seed_type="seasonal")]
        pool = [dataclasses.replace(item, major="가전", minor="소형가전") for item in pool]
        put(self.paths.seeds, seeds.seeds_to_dict(pool))
        put(self.paths.calendar, schedule.entries_to_dict([ts.example_entry(keywords=("예시 난방",), name="예시 난방 시기")]))

    def ledger_post(self, title="예시 이력 글", keywords=("예시 가습기",), ref="p1", channel="naver_a"):
        with open_for_write(self.paths.database) as store:
            store.sync_history([hs.HistoryRecord(channel=channel, title=title, keywords=keywords, date="2026-10-01", ref=ref, origin="naver_items")], now="2026-11-01T00:00:00Z")

    def plan(self, **kwargs):
        kwargs.setdefault("today", TODAY)
        return tp.plan_candidates(self.ctx, **kwargs)

    def generate(self, **kwargs):
        kwargs.setdefault("today", TODAY)
        kwargs.setdefault("confirmed", True)
        return tp.generate_candidates(self.ctx, **kwargs)

    def stored(self, channel=None):
        with open_read_only(self.paths.database) as store:
            return store.list_candidates(channel=channel)


def plan_of(result, channel):
    return next(item for item in result.plans if item.channel == channel)


class InputChecksTest(unittest.TestCase):
    def test_a_good_input_passes_and_none_means_not_given(self):
        self.assertEqual((tp.check_today(None), tp.check_target(None), tp.check_channel(None)), (None, None, None))
        self.assertEqual((tp.check_today("2026-11-05"), tp.check_target(1), tp.check_target(200), tp.check_channel("naver_a")), ("2026-11-05", 1, 200, "naver_a"))
        self.assertEqual((tp.check_channel("blogger_a"), tp.check_channel("blogger_b")), ("blogger_ko", "blogger_en"), "전략 문서의 별칭도 받는다")

    def test_wrong_inputs_are_content_errors_that_never_repeat_what_was_typed(self):
        for call, bad in ((tp.check_today, "2026-13-45"), (tp.check_today, "내일"), (tp.check_today, "2026-11-5"), (tp.check_today, 20261105), (tp.check_today, "1999-01-01"), (tp.check_today, "9999-12-31"),
                          (tp.check_today, KEY_LIKE), (tp.check_target, 0), (tp.check_target, -3), (tp.check_target, 201), (tp.check_target, True), (tp.check_target, 3.5), (tp.check_target, "5"),
                          (tp.check_channel, "naver_c"), (tp.check_channel, KEY_LIKE), (tp.check_channel, 7), (tp.check_channel, "NAVER_A")):
            with self.subTest(call=call.__name__, bad=str(bad)[:12]):
                with self.assertRaises(AppError) as caught:
                    call(bad)
                self.assertEqual(caught.exception.code, "CONTENT_INVALID")
                shown = str(caught.exception.slots) + str(caught.exception.detail)
                self.assertNotIn(str(bad), shown if len(str(bad)) > 6 else shown.replace(str(bad), "·"), "입력한 값을 되풀이하지 않는다")
                self.assertTrue(notice.is_clean(str(caught.exception.slots.get("항목", ""))), "화면 글에 목록 꼴·내부 코드가 없다")

    def test_the_service_checks_the_input_before_reading_anything(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = World(tmp)
            before = tree(tmp)
            for kwargs in ({"today": "2026-13-45"}, {"target": 0}, {"channel": "x"}):
                with self.subTest(kwargs=kwargs):
                    self.assertEqual(code_of(world.plan, **kwargs), "CONTENT_INVALID")
                    self.assertEqual(code_of(world.generate, **kwargs), "CONTENT_INVALID")
            self.assertEqual(code_of(tp.list_candidates, world.ctx, channel="x"), "CONTENT_INVALID")
            self.assertEqual(code_of(tp.list_candidates, world.ctx, status="DONE"), "CONTENT_INVALID")
            self.assertEqual(code_of(tp.list_candidates, world.ctx, band="BEST"), "CONTENT_INVALID")
            self.assertEqual(code_of(tp.review_holds, world.ctx, today="어제"), "CONTENT_INVALID")
            self.assertEqual(tree(tmp), before)


class RemainingSlotsConnectionTest(unittest.TestCase):
    """계획 11.1 — 서비스가 채널마다 기존 후보를 세어 남은 자리만큼만 새로 만든다(P2b 시나리오: 목표 3·기존 2 → 새 1)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.world = World(self.tmp.name)
        self.world.ledger_post()                                      # 후속 후보를 위한 기존 글 하나(장부에 둔다)

    def test_with_nothing_stored_the_whole_target_is_open_and_the_plan_matches_the_p2b_world(self):
        result = self.world.plan(channel="naver_a", target=3)
        plan = plan_of(result, "naver_a")
        self.assertEqual((plan.target, plan.slots.active_existing, plan.slots.pending_review, plan.slots.remaining), (3, 0, 0, 3))
        self.assertEqual(sorted(candidate.source_type for candidate in plan.candidates), ["follow_up", "seasonal", "seed"])
        self.assertEqual((plan.duplicates, result.saved, result.total), (0, False, 3))

    def test_after_saving_the_target_is_full_and_a_second_run_creates_nothing(self):
        first = self.world.generate(channel="naver_a", target=3)
        self.assertEqual((first.saved, first.total), (True, 3))
        self.assertEqual(len(self.world.stored("naver_a")), 3)
        second = self.world.generate(channel="naver_a", target=3)
        plan = plan_of(second, "naver_a")
        self.assertEqual((plan.slots.active_existing + plan.slots.pending_review, plan.slots.remaining, len(plan.candidates), second.total), (3, 0, 0, 0))
        self.assertEqual(len(self.world.stored("naver_a")), 3, "다시 해도 늘지 않는다")

    def test_a_rejected_candidate_gives_its_slot_back_but_is_never_made_again(self):
        self.world.generate(channel="naver_a", target=3)
        stored = self.world.stored("naver_a")
        with open_for_write(self.world.paths.database) as store:
            store.set_work_status(stored[0].candidate_id, "REJECTED")
        again = plan_of(self.world.plan(channel="naver_a", target=3), "naver_a")
        self.assertEqual((again.slots.active_existing + again.slots.pending_review, again.slots.remaining, again.slots.ignored), (2, 1, ((slots.WHY_REJECTED, 1),)))
        self.assertLessEqual(len(again.candidates), 1, "남은 자리(1)보다 많이 만들지 않는다")
        self.assertNotIn(stored[0].candidate_id, [candidate.candidate_id for candidate in again.candidates], "제외한 후보의 번호는 다시 만들지 않는다")

    def test_a_target_larger_than_the_stored_count_opens_exactly_the_difference(self):
        self.world.generate(channel="naver_a", target=3)
        plan = plan_of(self.world.plan(channel="naver_a", target=8), "naver_a")
        self.assertEqual(plan.slots.remaining, 5)
        self.assertEqual(slots.remaining_slots(8, plan.slots.active_existing, plan.slots.pending_review), 5)
        self.assertLessEqual(len(plan.candidates), 5)

    def test_slots_are_counted_per_channel_not_across_channels(self):
        self.world.generate(target=3)
        for channel in ("naver_a", "naver_b"):
            with self.subTest(channel=channel):
                plan = plan_of(self.world.plan(target=3), channel)
                mine = [item for item in self.world.stored() if item.channel == channel]
                counted = plan.slots.active_existing + plan.slots.pending_review
                self.assertEqual((counted, plan.slots.remaining), (len(mine), max(0, 3 - len(mine))))

    def test_disabled_channels_are_reported_but_never_planned(self):
        result = self.world.plan(target=3)
        for channel in ("github_pages", "blogger_en", "blogger_ko"):
            plan = plan_of(result, channel)
            self.assertEqual((plan.enabled, plan.slots, plan.candidates), (False, None, ()))
        self.assertEqual([plan.channel for plan in result.plans], ["github_pages", "blogger_en", "blogger_ko", "naver_a", "naver_b"])

    def test_draft_states_are_read_from_the_linked_post_flow_and_take_slots(self):
        self.world.generate(channel="naver_a", target=3)
        stored = self.world.stored("naver_a")
        with open_for_write(self.world.paths.database) as store:
            for candidate in stored[:2]:
                store.set_work_status(candidate.candidate_id, "SELECTED")
        base = plan_of(self.world.plan(channel="naver_a", target=3), "naver_a").slots
        self.assertEqual(base.remaining, 0)
        states = {stored[0].candidate_id: slots.DRAFTING, stored[1].candidate_id: slots.DRAFT_READY}
        counted = slots.count_slots(self.world.stored("naver_a"), 3, "2026-11-10T00:00:00Z", draft_states=states)
        self.assertEqual(counted.remaining, 0)

    def test_the_new_candidates_that_equal_an_existing_one_by_topic_are_dropped_and_counted(self):
        self.world.generate(channel="naver_a", target=3)
        stored = self.world.stored("naver_a")
        with mock.patch.object(tp.gen, "generate") as fake:
            twin = dataclasses.replace(stored[0], candidate_id="tc-naver_a-seed-ffffffffffffffff", seed_id="other-seed")
            fake.return_value = SimpleNamespace(candidates=(twin,), routes=(), dropped=(), notes=(), shortages=lambda: {})
            plan = plan_of(self.world.plan(channel="naver_a", target=10), "naver_a")
        self.assertEqual((len(plan.candidates), plan.duplicates), (0, 1), "번호는 달라도 같은 주제이면 같은 후보다 — 쓰지 않고 센다")


class DefaultDayAndTwinsTest(unittest.TestCase):
    def test_the_default_day_is_the_korean_date_not_the_utc_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = World(tmp)
            world.ctx.clock.now = world.ctx.clock.now.replace(hour=20, minute=0)          # 협정세계시 20시 = 한국 시간 다음 날 5시
            self.assertEqual(tp.today_of(world.ctx), "2026-11-03")
            self.assertEqual(tp.plan_candidates(world.ctx).today, "2026-11-03")
            self.assertEqual(tp.today_of(world.ctx, "2026-01-02"), "2026-01-02", "준 날짜가 먼저다")
            self.assertEqual(tp.now_stamp(world.ctx), "2026-11-02T20:00:12Z", "기준일을 안 주면 시계의 지금")
            self.assertEqual(tp.now_stamp(world.ctx, "2026-11-04"), "2026-11-04T00:00:00Z")

    def test_two_new_candidates_that_equal_each_other_are_reduced_to_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = World(tmp)
            first = world.plan(channel="naver_a", target=3)
            candidate = plan_of(first, "naver_a").candidates[0]
            twin = dataclasses.replace(candidate, candidate_id="tc-naver_a-seed-eeeeeeeeeeeeeeee", seed_id="other-seed")
            with mock.patch.object(tp.gen, "generate") as fake:
                fake.return_value = SimpleNamespace(candidates=(candidate, twin), routes=(), dropped=(), notes=(), shortages=lambda: {})
                plan = plan_of(world.plan(channel="naver_a", target=10), "naver_a")
            self.assertEqual(([item.candidate_id for item in plan.candidates], plan.duplicates), ([candidate.candidate_id], 1))


class ReadOnlyPromiseTest(unittest.TestCase):
    def test_the_reading_commands_create_nothing_when_there_is_no_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = World(tmp)
            before = tree(tmp)
            tp.status(world.ctx)
            world.plan()
            tp.check_files(world.ctx, today=TODAY)
            tp.top_candidates(world.ctx)
            tp.list_candidates(world.ctx)
            tp.review_holds(world.ctx, today=TODAY)
            self.assertEqual(code_of(tp.show_candidate, world.ctx, "1"), "TOPIC_CANDIDATE_NOT_FOUND")
            self.assertEqual(world.generate(confirmed=False).saved, False)
            self.assertEqual(tp.init_topics(world.ctx, confirmed=False).confirmed, False)
            self.assertEqual(tree(tmp), before, "아무 파일도 폴더도 만들어지지 않았다")
            self.assertFalse(world.paths.database.exists())
            self.assertFalse((Path(tmp) / "data" / "chanceblog.db").exists(), "글 보관함도 만들지 않는다")

    def test_the_reading_commands_leave_an_existing_store_byte_for_byte_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = World(tmp)
            world.generate(target=4)
            before = (digest(world.paths.database), world.paths.database.stat().st_mtime_ns, tree(tmp))
            tp.status(world.ctx)
            world.plan(target=9)
            tp.check_files(world.ctx, today=TODAY)
            tp.top_candidates(world.ctx)
            tp.list_candidates(world.ctx)
            tp.show_candidate(world.ctx, "1")
            tp.review_holds(world.ctx, today="2027-06-01")
            world.generate(confirmed=False, target=9)
            self.assertEqual((digest(world.paths.database), world.paths.database.stat().st_mtime_ns, tree(tmp)), before)

    def test_init_without_confirmation_only_lists_what_it_would_make_and_with_it_makes_only_missing_things(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = World(tmp, with_world=False)
            preview = tp.init_topics(world.ctx, confirmed=False)
            self.assertEqual((preview.made, preview.kept, preview.store_created), (layout.JSON_FILES, (), True))
            self.assertFalse(world.paths.folder.exists())
            for flag in (None, 1, "yes", 0):
                self.assertFalse(tp.init_topics(world.ctx, confirmed=flag).confirmed, "확인은 True 하나뿐이다")
            self.assertFalse(world.paths.folder.exists())
            done = tp.init_topics(world.ctx, confirmed=True)
            self.assertEqual((done.made, done.kept, done.store_created), (layout.JSON_FILES, (), True))
            self.assertEqual(sorted(os.listdir(world.paths.folder)), sorted(layout.USER_DATA_FILES))
            with open_read_only(world.paths.database) as store:
                self.assertEqual((store.schema_version, store.count()), (1, 0))
            again = tp.init_topics(world.ctx, confirmed=True)
            self.assertEqual((again.made, again.kept, again.store_created), ((), layout.JSON_FILES, False))

    def test_generate_without_confirmation_is_exactly_the_preview(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = World(tmp)
            preview = world.generate(confirmed=False, target=4)
            planned = world.plan(target=4)
            self.assertEqual(preview.to_dict(), planned.to_dict())
            for flag in (None, 1, "yes", "True", 0):
                self.assertFalse(world.generate(confirmed=flag, target=4).saved, repr(flag))
            self.assertFalse(world.paths.database.exists())


class OneTransactionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.world = World(self.tmp.name)
        self.world.ledger_post()                                       # 저장 전부터 장부에 있는 기록 하나
        posts = self.world.repo / "_posts" / "예시"
        posts.mkdir(parents=True)
        (posts / "2026-10-01-KR-100000.md").write_text('---\nlayout: post\ntitle: "예시 사이트 글"\ncategory: "예시"\ntags: ["가"]\nlang: "ko"\nimage: "https://example.invalid/a.jpg"\n---\n본문\n', encoding="utf-8")
        self.pre_ledger = [record.title for record in self.ledger()]

    def ledger(self):
        with open_read_only(self.world.paths.database) as store:
            return store.history_records()

    def test_a_failure_while_computing_the_second_channel_saves_nothing_at_all(self):
        real = tp.gen.generate
        calls = []

        def second_fails(*args, **kwargs):
            calls.append(1)
            if len(calls) >= 2:
                raise RuntimeError("두 번째 채널을 계산하다 멈춤")
            return real(*args, **kwargs)

        with mock.patch.object(tp.gen, "generate", side_effect=second_fails):
            with self.assertRaises(RuntimeError):
                self.world.generate(target=4)
        self.assertEqual(self.world.stored(), [], "첫 채널의 후보도 저장되지 않았다")
        with open_read_only(self.world.paths.database) as store:
            self.assertEqual((store.hold_stays(), store.count()), ([], 0))
        self.assertEqual([record.title for record in self.ledger()], self.pre_ledger, "이번에 읽은 블로그 글도 장부에 올라가지 않았다(저장 전 장부 그대로)")

    def test_a_failure_in_the_middle_of_writing_leaves_no_partial_save(self):
        real = TopicStore._insert
        counter = []

        def third_fails(self_, db, candidate, now):
            counter.append(1)
            if len(counter) == 3:
                raise AppError("DISK_FULL", detail="일부러 낸 실패")
            return real(self_, db, candidate, now)

        with mock.patch.object(TopicStore, "_insert", third_fails):
            self.assertEqual(code_of(self.world.generate, target=6), "DISK_FULL")
        with open_read_only(self.world.paths.database) as store:
            self.assertEqual(store.count(), 0)
        self.assertEqual([record.title for record in self.ledger()], self.pre_ledger)

    def test_the_plan_is_computed_from_the_candidates_read_after_the_write_lock_was_taken(self):
        self.world.generate(channel="naver_a", target=3)
        before = len(self.world.stored("naver_a"))
        seen = []
        real = tp._plan_channels

        def spy(*args):
            seen.append(len(args[3]))                                  # existing
            return real(*args)

        with mock.patch.object(tp, "_plan_channels", spy):
            self.world.generate(channel="naver_a", target=3)
        self.assertIn(before, seen, "저장 트랜잭션 안에서 지금 있는 후보를 읽어 남은 자리를 센다")

    def test_candidates_another_window_saved_after_the_first_read_are_counted_inside_the_transaction(self):
        planned = tp.plan_candidates(self.world.ctx, today=TODAY, target=3, channel="naver_a")
        rival = [candidate for item in planned.plans for candidate in item.candidates]
        self.assertTrue(rival)
        database = self.world.paths.database

        class OtherWindow:
            name = "다른 창을 흉내 내는 공급자"

            def __init__(inner):                                          # noqa: N805
                inner.done = False

            def read(inner, keyword, today):                              # noqa: N805
                if not inner.done:                                        # 서비스가 처음 후보를 읽은 뒤·저장 트랜잭션 전에 다른 창이 같은 후보를 먼저 저장했다
                    inner.done = True
                    with open_for_write(database) as other:
                        other.add_candidates(lambda existing: rival, now="2026-11-10T00:00:00Z")
                return trend.NOT_QUERIED

        result = tp.generate_candidates(self.world.ctx, confirmed=True, today=TODAY, target=3, channel="naver_a", trend=OtherWindow())
        self.assertTrue(result.saved)
        stored = self.world.stored("naver_a")
        self.assertEqual(sorted(c.candidate_id for c in stored), sorted(c.candidate_id for c in rival), "트랜잭션 안에서 다시 읽은 후보로 남은 자리를 세어 같은 후보를 또 만들지 않는다")
        self.assertEqual([c for plan in result.plans for c in plan.candidates], [], "남은 자리가 없어 새 후보가 없다")

    def test_two_runs_at_the_same_time_do_not_duplicate_and_do_not_fail(self):
        errors, barrier = [], threading.Barrier(2)

        def run():
            try:
                barrier.wait(timeout=10)
                tp.generate_candidates(self.world.ctx, confirmed=True, today=TODAY, target=4)
            except BaseException as error:
                errors.append(repr(error))

        threads = [threading.Thread(target=run) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(120)
        self.assertEqual(errors, [])
        alone = tempfile.TemporaryDirectory()
        self.addCleanup(alone.cleanup)
        reference = World(alone.name)
        reference.ledger_post()
        reference.generate(target=4)
        reference.generate(target=4)                                   # 한 곳씩 차례로 두 번 한 것과 같아야 한다 — 뒤에 잠금을 잡은 쪽은 앞 쪽이 저장한 것을 보고 남은 자리만 채운다
        ids = [c.candidate_id for c in self.world.stored()]
        self.assertEqual(len(ids), len(set(ids)), "겹치지 않는다")
        self.assertEqual(sorted(ids), sorted(c.candidate_id for c in reference.stored()))
        for channel in ("naver_a", "naver_b"):
            self.assertLessEqual(len(self.world.stored(channel)), 4, "목표를 넘지 않는다")

    def test_the_candidate_ids_stay_unique_when_the_same_run_is_repeated(self):
        for _ in range(3):
            self.world.generate(target=5)
        ids = [item.candidate_id for item in self.world.stored()]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertLessEqual(len([item for item in self.world.stored("naver_a")]), 5)


class BlogHistoryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.world = World(self.tmp.name)
        self.repo = self.world.repo

    def write_post(self, name="2026-10-01-KR-100000.md", title="예시 제목입니다", tags='["가", "나"]'):
        folder = self.repo / "_posts" / "예시"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / name).write_text(f'---\nlayout: post\ntitle: "{title}"\ncategory: "예시"\ntags: {tags}\nlang: "ko"\nimage: "https://example.invalid/a.jpg"\n---\n본문입니다\n', encoding="utf-8")

    def test_check_looks_at_every_field_of_a_published_post_and_hides_a_key_shaped_post_number(self):
        self.write_post(name="2026-10-01-KR-100001.md", tags=f'["가", "{KEY_LIKE}"]')               # 키는 태그(키워드)에만
        self.write_post(name=f"2026-10-02-KR-{KEY_LIKE}.md")                                         # 키는 파일 이름(글 번호)에만
        (self.repo / "blogger_history.json").write_text(json.dumps([
            {"date": "2026-10-03", "topic": "예시", "title": "Example A", "labels": ["a"], "url": f"https://example.blogspot.com/x?token={KEY_LIKE}", "post_id": "111"},    # 키는 주소에만
            {"date": "2026-10-04", "topic": "예시", "title": "Example B", "labels": ["a"], "url": "https://example.blogspot.com/y", "post_id": KEY_LIKE},                 # 키는 글 번호(post_id)에만
            {"date": "2026-10-05", "topic": f"예시 {KEY_LIKE}", "title": "Example C", "labels": ["a"], "url": "https://example.blogspot.com/z", "post_id": "333"},        # 키는 주제에만
            {"date": "2026-10-06", "topic": "예시", "title": "Example D", "labels": ["a"], "url": "https://example.blogspot.com/w", "post_id": "444"},                    # 정상
        ]), encoding="utf-8")
        result = tp.check_files(self.world.ctx, today=TODAY)
        text = " ".join(result.public_keyed)
        self.assertEqual(len(result.public_keyed), 5, "제목만이 아니라 키워드·주소·주제·글 번호까지 훑는다")
        for number in ("2026-10-01-KR-100001", "111", "333"):
            self.assertIn(f"‘{number}’", text, "글 번호만 알린다")
        self.assertEqual(text.count("‘(이름 가림)’"), 2, "글 번호 자체가 키 모양이면(파일 이름·post_id) 가려서 알린다")
        self.assertNotIn(KEY_LIKE, text + json.dumps(result.to_dict()["public_key_shaped"], ensure_ascii=False), "낱말은 되풀이하지 않는다")
        self.assertNotIn("444", text, "정상 글은 알리지 않는다")

    def test_a_key_shaped_published_title_is_kept_in_the_ledger_without_blocking_the_backup(self):
        """A-N1: 이미 공개된 블로그 글 제목에 키 모양 낱말이 있어도 generate 가 장부에 올리고 백업이 영구히 막히지 않는다(D-75)."""
        self.write_post(title=f"예시 {KEY_LIKE}")
        self.write_post(name="2026-10-02-KR-100001.md", title="예시 정상 제목입니다")
        self.world.generate(target=4)
        with open_read_only(self.world.paths.database) as store:
            titles = [record.title for record in store.history_records()]
        self.assertTrue(any(KEY_LIKE in title for title in titles), "공개된 글의 값은 그대로 장부에 담긴다")
        self.assertIn("예시 정상 제목입니다", titles)
        self.assertTrue(tp.backup_topics(self.world.ctx).path.is_dir(), "장부의 키 모양은 백업을 막지 않는다")
        shutil.rmtree(self.repo / "_posts")
        self.assertTrue(tp.backup_topics(self.world.ctx).path.is_dir(), "블로그에서 글이 사라져도 마찬가지다")

    def test_check_names_the_published_post_number_and_never_repeats_the_word(self):
        self.assertEqual(tp.check_files(self.world.ctx, today=TODAY).public_keyed, (), "정상 글만 있으면 알릴 것이 없다")
        self.write_post(title=f"예시 {KEY_LIKE}")
        result = tp.check_files(self.world.ctx, today=TODAY)
        self.assertTrue(result.ok)
        self.assertEqual(len(result.public_keyed), 1)
        self.assertIn("100000", result.public_keyed[0], "글 번호만 알린다")
        self.assertNotIn(KEY_LIKE, " ".join(result.public_keyed) + json.dumps(result.to_dict()["public_key_shaped"], ensure_ascii=False))
        self.assertEqual(result.keyed, (), "씨앗·후보가 아니라 발행한 글의 키 모양은 따로 알린다(저장·백업을 막지 않는다)")

    def test_the_five_channels_are_read_from_their_own_places_and_only_read(self):
        self.write_post()
        (self.repo / "blogger_history.json").write_text(json.dumps([{"date": "2026-10-02", "topic": "예시", "title": "Example Post", "labels": ["a"], "url": "https://example.blogspot.com/x", "post_id": "123"}]), encoding="utf-8")
        ss.naver_profiles(self.world.ctx)
        pid = projects.new_project(self.world.ctx, "예시 네이버 글", ss.ko_text()).project_id
        review.request_review(self.world.ctx, pid, "naver_a")
        review.issue_naver_package(self.world.ctx, pid, "naver_a")
        review.record_naver_published(self.world.ctx, pid, "naver_a", "https://blog.naver.com/exampleaaa/223000000001")
        before = tree(self.repo)
        reading = tp.read_blog_history(self.world.ctx)
        self.assertEqual(tree(self.repo), before, "블로그 저장소는 읽기만 한다")
        by = {item.channel: item for item in reading.channels}
        self.assertEqual((by["github_pages"].state, by["github_pages"].count), ("read", 1))
        self.assertEqual((by["blogger_en"].state, by["blogger_en"].count), ("read", 1))
        self.assertEqual((by["blogger_ko"].state, by["naver_a"].state, by["naver_a"].count, by["naver_b"].count), ("missing", "read", 1, 0))
        titles = {record.channel: record.title for record in reading.records}
        self.assertEqual(titles, {"github_pages": "예시 제목입니다", "blogger_en": "Example Post", "naver_a": "예시 네이버 글"})
        post = next(record for record in reading.records if record.channel == "github_pages")
        self.assertEqual((post.keywords, post.date, post.language), (("가", "나"), "2026-10-01", "ko"))
        naver = next(record for record in reading.records if record.channel == "naver_a")
        self.assertEqual((naver.url, naver.ref), ("https://blog.naver.com/exampleaaa/223000000001", pid))

    def test_what_cannot_be_read_is_skipped_with_a_plain_warning_and_never_stops_the_reading(self):
        self.write_post()
        (self.repo / "blogger_ko_history.json").write_text("{broken", encoding="utf-8")
        (self.repo / "blogger_history.json").write_text('{"not": "a list"}', encoding="utf-8")
        big = self.repo / "_posts" / "예시" / "2026-10-03-KR-100001.md"
        big.write_bytes(b"x" * (tp.MAX_POST_BYTES + 1))
        (self.repo / "_posts" / "예시" / "2026-10-04-KR-100002.md").write_bytes(b"\xff\xfe\x00 not utf8")
        reading = tp.read_blog_history(self.world.ctx)
        by = {item.channel: item for item in reading.channels}
        self.assertEqual((by["blogger_ko"].state, by["blogger_en"].state, by["github_pages"].state, by["github_pages"].count), ("unreadable", "unreadable", "read", 1))
        self.assertTrue(any("Blogger 한글" in line for line in reading.warnings))
        self.assertTrue(any("건너뛰었습니다" in line and "GitHub Pages" in line for line in reading.warnings))
        for line in reading.warnings:
            self.assertTrue(notice.is_clean(line), line)

    def test_without_a_connected_blog_repository_the_blog_channels_say_so(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = World(tmp, repo="")
            by = {item.channel: item.state for item in tp.read_blog_history(world.ctx).channels}
            self.assertEqual((by["github_pages"], by["blogger_en"], by["blogger_ko"], by["naver_a"]), ("not_connected", "not_connected", "not_connected", "no_store"))

    def test_the_ledger_keeps_what_was_read_and_is_merged_with_a_fresh_reading(self):
        self.write_post()
        self.world.generate(target=2)
        with open_read_only(self.world.paths.database) as store:
            ledger = store.history_records()
        self.assertEqual([record.title for record in ledger if record.channel == "github_pages"], ["예시 제목입니다"], "읽은 이력은 저장할 때 장부에도 올라간다")
        for path in (self.repo / "_posts").rglob("*.md"):
            path.unlink()                                                  # 블로그 쪽 글이 없어져도
        self.assertEqual(tp.read_blog_history(self.world.ctx).records, ())
        merged = tp.merge_history((), ledger)
        self.assertEqual([record.title for record in merged if record.channel == "github_pages"], ["예시 제목입니다"], "장부에는 남아 중복 검사에 계속 쓰인다")
        fresh = dataclasses.replace(next(record for record in ledger if record.channel == "github_pages"), title="새로 읽은 제목")
        again = tp.merge_history((fresh,), ledger)
        self.assertEqual([record.title for record in again if record.ref == fresh.ref], ["새로 읽은 제목"], "같은 기록은 이번에 읽은 것이 이긴다")
        self.assertEqual(tp.merge_history(tuple(reversed(ledger)), ledger), tp.merge_history(ledger, tuple(reversed(ledger))), "순서와 상관없이 같은 결과")


class TrendConnectionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.world = World(self.tmp.name)

    def candidates(self, **kwargs):
        return plan_of(self.world.plan(channel="naver_a", target=8, **kwargs), "naver_a").candidates

    def test_no_provider_and_the_none_provider_give_the_same_plan(self):
        self.assertEqual([c.to_dict() for c in self.candidates()], [c.to_dict() for c in self.candidates(trend=trend.NoTrend())])

    def test_a_value_provider_fills_the_interest_columns_and_a_failing_one_does_not_stop_the_plan(self):
        base = {c.candidate_id: c for c in self.candidates()}
        valued = self.candidates(trend=trend.FakeTrend("value"))
        self.assertTrue(any(c.trend_ratio == 73 and c.trend_status == "rising" for c in valued))
        self.assertTrue(all(c.search_demand_count is None for c in valued), "상대값은 실제 검색 횟수 칸으로 흐르지 않는다")
        self.assertNotEqual([c.scores.final for c in valued], [base[c.candidate_id].scores.final for c in valued if c.candidate_id in base])
        for scenario in ("unavailable", "slow", "insufficient"):
            with self.subTest(scenario=scenario):
                made = self.candidates(trend=trend.FakeTrend(scenario))
                self.assertEqual(len(made), len(base))
                self.assertTrue(all(c.trend_ratio is None for c in made))
        self.assertTrue(all(c.data_status == "unavailable" for c in self.candidates(trend=trend.FakeTrend("unavailable"))))

        class Boom:
            name = "오류를 내는 공급자"

            def read(self, keyword, today):
                raise RuntimeError("연결 실패")

        self.assertEqual(len(self.candidates(trend=Boom())), len(base))

    def test_the_provider_is_called_outside_the_write_lock_and_the_notes_come_back(self):
        busy = []

        class Probe:
            name = "자물쇠를 보는 공급자"

            def __init__(self, path):
                self.path = path
                self.calls = 0

            def read(inner, keyword, today):                              # noqa: N805
                inner.calls += 1
                try:
                    with open_for_write(inner.path, busy_seconds=0.2) as other:                       # 저장 트랜잭션이 쓰기 잠금을 쥐고 있으면 여기서 막힌다
                        other.sync_history([], now="2026-11-01T00:00:00Z")
                except AppError as error:
                    busy.append(error.code)
                return trend.FakeTrend("value").read(keyword, today)

        probe = Probe(self.world.paths.database)
        with open_for_write(self.world.paths.database):
            pass
        result = tp.generate_candidates(self.world.ctx, confirmed=True, today=TODAY, target=4, channel="naver_a", trend=probe)
        self.assertTrue(probe.calls > 0)
        self.assertEqual(busy, [], "관심도 조회는 쓰기 잠금 밖에서 한다")
        self.assertTrue(result.saved)
        self.assertTrue(all(isinstance(note, str) for plan in result.plans for note in plan.trend_notes))


class ZeroByteStoreTest(unittest.TestCase):
    """0바이트 `topic_engine.db`(만들다 멈춘 흔적) — 쓰기 열기가 '새 파일' 로 보는 것과 같은 정의로 읽기 명령도 '아직 없는 것' 으로 본다(D-69)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.world = World(self.tmp.name)
        self.world.paths.folder.mkdir(parents=True, exist_ok=True)
        self.world.paths.database.write_bytes(b"")

    def test_every_reading_command_reports_it_as_empty_and_changes_nothing(self):
        before = (tree(self.tmp.name), self.world.paths.database.stat().st_mtime_ns)
        self.assertEqual(tp.status(self.world.ctx).store_state, "empty")
        self.assertEqual(self.world.plan(target=3).store_state, "empty")
        listed = tp.list_candidates(self.world.ctx)
        self.assertEqual((listed.total, listed.store_state), (0, "empty"))
        self.assertEqual(tp.top_candidates(self.world.ctx).store_state, "empty")
        self.assertEqual(tp.review_holds(self.world.ctx, today=TODAY).store_state, "empty")
        self.assertEqual(code_of(tp.show_candidate, self.world.ctx, "1"), "TOPIC_CANDIDATE_NOT_FOUND")
        self.assertTrue(any("비어 있습니다" in note for note in self.world.plan(target=3).notes))
        self.assertEqual((tree(self.tmp.name), self.world.paths.database.stat().st_mtime_ns), before, "읽기 명령은 0바이트 파일을 바꾸지도 만들지도 않는다")

    def test_the_commands_that_save_create_a_real_store_over_it(self):
        result = self.world.generate(target=3)
        self.assertTrue(result.saved)
        self.assertGreater(len(self.world.stored()), 0)
        self.assertGreater(self.world.paths.database.stat().st_size, 0)
        other = tempfile.TemporaryDirectory()
        self.addCleanup(other.cleanup)
        second = World(other.name)
        second.paths.folder.mkdir(parents=True, exist_ok=True)
        second.paths.database.write_bytes(b"")
        preview = tp.init_topics(second.ctx, confirmed=False)
        self.assertTrue(preview.store_created, "0바이트는 만들 예정으로 알린다")
        done = tp.init_topics(second.ctx, confirmed=True)
        self.assertTrue(done.store_created)
        self.assertEqual((tp.status(second.ctx).store_state, tp.status(second.ctx).store_version), ("ready", 1))


class ZeroByteSettingsFileTest(unittest.TestCase):
    """0바이트 설정 JSON 은 '아직 없음' 으로 본다 — `init --yes` 가 기본 틀로 채우고 내용이 있는 파일은 읽을 수 없어도 건드리지 않는다(D-78)."""

    def test_init_fills_a_zero_byte_settings_file_with_the_default_and_leaves_a_file_with_content_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = World(tmp, with_world=False)
            world.paths.folder.mkdir(parents=True, exist_ok=True)
            world.paths.seeds.write_bytes(b"")
            world.paths.calendar.write_bytes(b"not json at all")                       # 내용이 있는 틀린 파일 — 절대 건드리지 않는다
            preview = tp.init_topics(world.ctx, confirmed=False)
            self.assertIn(layout.SEEDS_FILE, preview.made, "0바이트는 만들 것으로 센다")
            self.assertIn(layout.CALENDAR_FILE, preview.kept)
            self.assertEqual(world.paths.seeds.stat().st_size, 0, "미리 보기는 아무것도 바꾸지 않는다")
            reason = next(item.reason for item in tp.check_files(world.ctx).files if item.name == layout.SEEDS_FILE)
            self.assertIn("topics init --yes", reason, "읽을 수 없다고만 하지 않고 채우는 길을 알려 준다")
            result = tp.init_topics(world.ctx, confirmed=True)
            self.assertIn(layout.SEEDS_FILE, result.made)
            self.assertIn(layout.CALENDAR_FILE, result.kept)
            self.assertEqual(json.loads(world.paths.seeds.read_text(encoding="utf-8"))["seeds"], [])
            self.assertEqual(world.paths.calendar.read_bytes(), b"not json at all", "내용이 있는 파일은 읽을 수 없어도 그대로다")

    def test_init_leaves_every_file_with_any_content_alone_and_a_folder_too(self):
        cases = {"BOM 만": b"\xef\xbb\xbf", "빈 JSON 개체": b"{}", "줄바꿈 하나": b"\n", "공백 하나": b" ", "글자 하나": b"x"}
        for label, content in cases.items():
            with self.subTest(label=label):
                with tempfile.TemporaryDirectory() as tmp:
                    world = World(tmp, with_world=False)
                    world.paths.folder.mkdir(parents=True, exist_ok=True)
                    world.paths.seeds.write_bytes(content)
                    self.assertIn(layout.SEEDS_FILE, tp.init_topics(world.ctx, confirmed=False).kept, "미리 보기에서도 이미 있는 파일이다")
                    self.assertIn(layout.SEEDS_FILE, tp.init_topics(world.ctx, confirmed=True).kept)
                    self.assertEqual(world.paths.seeds.read_bytes(), content, "0바이트가 아니면 한 바이트도 바꾸지 않는다")
        with tempfile.TemporaryDirectory() as tmp:
            world = World(tmp, with_world=False)
            world.paths.folder.mkdir(parents=True, exist_ok=True)
            world.paths.seeds.mkdir()
            self.assertIn(layout.SEEDS_FILE, tp.init_topics(world.ctx, confirmed=False).kept, "폴더는 빈 파일이 아니다")
            self.assertIn(layout.SEEDS_FILE, tp.init_topics(world.ctx, confirmed=True).kept)
            self.assertTrue(world.paths.seeds.is_dir())


class KeyShapedSeedTest(unittest.TestCase):
    """키·토큰 모양 낱말이 든 씨앗은 후보로 저장하지 않는다(D-68) — 후보는 한 번 저장되면 지우는 길이 없어 백업이 영원히 막히기 때문이다."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.world = World(self.tmp.name)

    def key_into_first_seed(self):
        data = json.loads(self.world.paths.seeds.read_text(encoding="utf-8"))
        data["seeds"][0]["keyword"] = f"예시 {KEY_LIKE}"
        put(self.world.paths.seeds, data)
        return data

    def test_a_key_shaped_seed_never_reaches_the_store_while_the_other_seeds_are_saved_and_the_backup_still_works(self):
        data = self.key_into_first_seed()
        preview = self.world.plan(target=6)
        self.assertTrue(any("‘g1’" in line and "후보를 만들지 않았습니다" in line for line in preview.notes), "미리 보기에서도 알린다")
        self.assertFalse(self.world.paths.database.exists(), "미리 보기는 아무것도 만들지 않는다")
        result = self.world.generate(target=6)
        shown = [line for line in result.notes if "후보를 만들지 않았습니다" in line]
        self.assertEqual(len(shown), 1)
        self.assertIn("‘g1’", shown[0], "씨앗 번호만 알린다 — 낱말은 되풀이하지 않는다")
        self.assertEqual([name for plan in result.plans for name in plan.withheld], [], "후보를 만들기 전에 뺐으므로 저장 직전 거름에는 걸릴 것이 없다(방어선은 따로 시험한다 — D-77)")
        stored = self.world.stored()
        self.assertTrue(stored, "다른 씨앗의 후보는 정상으로 저장된다")
        self.assertFalse(any(KEY_LIKE in json.dumps(item.to_dict(), ensure_ascii=False) for item in stored))
        self.assertNotIn(KEY_LIKE, " ".join(result.notes) + json.dumps(result.to_dict()["notes"], ensure_ascii=False), "알림에는 씨앗 번호만 있고 낱말은 없다")
        self.assertEqual(code_of(tp.backup_topics, self.world.ctx), "TOPIC_BACKUP_BLOCKED", "씨앗 파일에 키 모양이 남아 있는 동안은 백업이 막힌다")
        data["seeds"][0]["keyword"] = "예시 고친 씨앗"
        put(self.world.paths.seeds, data)
        self.assertTrue(tp.backup_topics(self.world.ctx).path.is_dir(), "씨앗 파일에서 지우면 곧바로 백업이 된다 — 보관함은 깨끗하다")

    def test_check_names_the_seed_and_never_repeats_the_word(self):
        clean = tp.check_files(self.world.ctx, today=TODAY)
        self.assertEqual(clean.keyed, ())
        self.key_into_first_seed()
        result = tp.check_files(self.world.ctx, today=TODAY)
        self.assertTrue(result.ok, "읽을 수 있는 파일이라 검사는 통과하고 키 모양은 따로 알린다")
        self.assertEqual(len(result.keyed), 1)
        self.assertIn("g1", result.keyed[0])
        self.assertNotIn(KEY_LIKE, " ".join(result.keyed) + json.dumps(result.to_dict()["key_shaped"], ensure_ascii=False), "알림에는 씨앗 번호만 있고 낱말은 없다")

    def test_a_seed_whose_only_key_shape_is_its_id_or_an_excluded_keyword_is_left_out_before_the_candidates_are_made(self):
        """씨앗의 어느 칸에서든 키 모양이면 후보를 만들기 전에 뺀다 — 낱말 칸만 보지 않는다. 번호 자체가 키 모양이면 그 번호도 가려 알린다(D-77)."""
        excluded = "AK" + "IA" + "B" * 16                                          # 제외 키워드 칸은 30자까지라 짧은 키 모양을 쓴다
        for label, changes, shown in (("씨앗 번호", {"seed_id": KEY_LIKE}, "(이름 가림)"), ("제외 키워드", {"excluded_keywords": (excluded,)}, "ex-seed-001")):
            with self.subTest(label=label):
                with tempfile.TemporaryDirectory() as tmp:
                    world = World(tmp)
                    pool = [dataclasses.replace(ts.example_seed(seed_id=f"n{i}", keyword=word), major="가전", minor="소형가전") for i, word in enumerate(["예시 공기청정기", "예시 가습기 관리"])]
                    pool.append(dataclasses.replace(ts.example_seed(keyword="예시 로봇청소기", **changes), major="가전", minor="소형가전"))
                    put(world.paths.seeds, seeds.seeds_to_dict(pool))
                    result = world.generate(target=6)
                    shown_lines = [line for line in result.notes if "후보를 만들지 않았습니다" in line]
                    self.assertEqual(len(shown_lines), 1)
                    self.assertIn(f"씨앗 1개(씨앗 ‘{shown}’)", shown_lines[0])
                    self.assertEqual([name for plan in result.plans for name in plan.withheld], [], "후보를 만들기 전에 뺐으므로 저장 직전 거름에는 걸릴 것이 없다")
                    self.assertTrue(world.stored(), "다른 씨앗의 후보는 저장된다")
                    text = " ".join(result.notes) + json.dumps(result.to_dict(), ensure_ascii=False)
                    for word in (KEY_LIKE, excluded):
                        self.assertNotIn(word, text, "안내에 낱말이 없다")
                        self.assertNotIn(word.encode("utf-8"), world.paths.database.read_bytes(), "보관함에도 없다")

    def test_two_key_shaped_seeds_are_counted_and_the_same_shown_name_is_listed_once(self):
        other = "AI" + "za" + "E" * 35
        data = json.loads(self.world.paths.seeds.read_text(encoding="utf-8"))
        data["seeds"][0]["seed_id"], data["seeds"][1]["seed_id"] = KEY_LIKE, other             # 둘 다 번호가 키 모양이라 같은 '(이름 가림)' 으로 보인다
        put(self.world.paths.seeds, data)
        line = next(item for item in self.world.plan(target=6).notes if "후보를 만들지 않았습니다" in item)
        self.assertIn("씨앗 2개(씨앗 ‘(이름 가림)’)", line, "개수는 센 만큼, 같은 이름은 한 번만")
        self.assertNotIn("‘(이름 가림)’·‘(이름 가림)’", line)
        self.assertNotIn(KEY_LIKE + other, line)

    def test_a_key_shaped_seed_does_not_take_the_share_of_the_other_seeds_of_the_same_channel(self):
        """B-N1: 키 모양 씨앗의 후보가 저장 직전에야 걸러지면 그 몫만큼 같은 채널 다른 씨앗의 후보가 밀려난다 — 작은 목표에서도 키 모양 씨앗이 없는 것과 같은 개수가 저장돼야 한다(D-77)."""
        def stored_by_channel(with_key):
            with tempfile.TemporaryDirectory() as tmp:
                world = World(tmp)
                pool = [dataclasses.replace(ts.example_seed(seed_id=f"n{i}", keyword=word), major="가전", minor="소형가전") for i, word in enumerate(["예시 공기청정기", "예시 가습기 관리", "예시 로봇청소기"])]
                if with_key:
                    pool.insert(0, dataclasses.replace(ts.example_seed(seed_id="k1", keyword=f"예시 {KEY_LIKE}"), major="가전", minor="소형가전"))
                put(world.paths.seeds, seeds.seeds_to_dict(pool))
                for _ in range(4):
                    world.generate(target=6)
                counts = {}
                for item in world.stored():
                    counts[item.channel] = counts.get(item.channel, 0) + 1
                    self.assertNotIn(KEY_LIKE, json.dumps(item.to_dict(), ensure_ascii=False))
                return counts

        baseline = stored_by_channel(False)
        self.assertGreater(sum(baseline.values()), 4, "기준: 정상 씨앗만으로 여러 후보가 저장된다")
        self.assertEqual(stored_by_channel(True), baseline, "키 모양 씨앗이 하나 끼어도 정상 씨앗의 후보는 같은 개수로 저장된다")

    def test_every_seed_being_key_shaped_is_said_so_instead_of_claiming_there_are_no_seeds(self):
        data = json.loads(self.world.paths.seeds.read_text(encoding="utf-8"))
        for number, item in enumerate(data["seeds"]):
            item["keyword"] = f"예시 {KEY_LIKE}{number}"                              # 낱말이 서로 달라야 씨앗 목록 검사를 통과한다
        put(self.world.paths.seeds, data)
        notes = " ".join(self.world.plan(target=6).notes)
        self.assertIn("후보를 만들지 않았습니다", notes)
        self.assertNotIn("씨앗이 하나도 없습니다", notes)

    def test_the_last_line_of_defence_still_withholds_a_key_shaped_candidate_and_hides_a_key_shaped_seed_id(self):
        keyed_id = SimpleNamespace(seed_id=KEY_LIKE, to_dict=lambda: {"topic": f"예시 {KEY_LIKE}"})
        clean = SimpleNamespace(seed_id="g9", to_dict=lambda: {"topic": "예시 정상 주제"})
        safe, names = tp._withhold_key_shaped([keyed_id, clean])
        self.assertEqual(safe, (clean,))
        self.assertEqual(names, ("(이름 가림)",), "씨앗 번호 자체가 키 모양이면 그 번호도 가린다")
        keyed_topic = SimpleNamespace(seed_id="g1", to_dict=lambda: {"topic": f"예시 {KEY_LIKE}"})
        self.assertEqual(tp._withhold_key_shaped([keyed_topic]), ((), ("g1",)))

    def test_a_key_shaped_seed_id_is_not_shown_either(self):
        shown = tp._shown_seed(KEY_LIKE)
        self.assertEqual(shown, "(이름 가림)")
        self.assertEqual(tp._shown_seed(None), "(이름 가림)")
        self.assertEqual(tp._shown_seed("g1"), "g1")


class OrdinalAndFillTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.world = World(self.tmp.name)

    def ordinals(self):
        return [(row.ordinal, row.candidate.candidate_id) for row in tp.list_candidates(self.world.ctx).rows]

    def test_a_second_save_on_the_same_day_does_not_move_the_ordinals_of_what_was_saved_before(self):
        self.world.generate(channel="naver_a", target=2)
        first = self.ordinals()
        self.world.generate(channel="naver_a", target=6)                                 # 기준일이 같아 만든 시각도 같다
        second = self.ordinals()
        self.assertGreater(len(second), len(first))
        self.assertEqual(second[:len(first)], first, "먼저 저장한 후보의 순번은 그대로이고 새 후보가 뒤에 붙는다")
        self.assertEqual([number for number, _id in second], list(range(1, len(second) + 1)))

    def test_a_partly_filled_channel_is_filled_up_by_the_next_saves_one_run_after_another(self):
        totals, seen = [], []
        for target in (2, 4, 6, 6):
            result = self.world.generate(channel="naver_a", target=target)
            plan = plan_of(result, "naver_a")
            seen.append((len(plan.candidates), plan.slots.remaining))
            totals.append(len(self.world.stored("naver_a")))
        self.assertEqual(totals, [1, 3, 5, 6], "서비스가 기존 후보를 `generate(existing=…)` 에 넘겨야 두 번째부터도 새 후보가 생긴다(넘기지 않으면 첫 후보만 되풀이해 거른다)")
        self.assertEqual([new for new, _left in seen], [1, 2, 2, 1])
        ids = [item.candidate_id for item in self.world.stored("naver_a")]
        self.assertEqual(len(ids), len(set(ids)))

    def test_the_candidate_errors_carry_their_help_in_the_item_not_in_the_hidden_detail(self):
        rows = [tp.Row(1, ts.rated(70, candidate_id="tc-naver_a-seed-aaaa000000000001", channel="naver_a", cluster="c1"), False),
                tp.Row(2, ts.rated(70, candidate_id="tc-naver_a-seed-aaaa000000000002", channel="naver_a", cluster="c2"), False)]
        with self.assertRaises(AppError) as missing:
            tp.resolve(rows, "9")
        self.assertEqual(missing.exception.code, "TOPIC_CANDIDATE_NOT_FOUND")
        self.assertIn("후보는 2개뿐입니다", missing.exception.slots["항목"])
        with self.assertRaises(AppError) as ambiguous:
            tp.resolve(rows, "aaaa")
        self.assertEqual(ambiguous.exception.code, "TOPIC_CANDIDATE_AMBIGUOUS")
        self.assertIn("겹치는 후보: 순번 1(aaaa0000) · 순번 2(aaaa0000)", ambiguous.exception.slots["항목"], "겹치는 후보는 화면에 안 나오는 세부가 아니라 문구에 있다")

    def test_the_restore_confirmation_says_in_its_item_what_will_change(self):
        self.world.generate(target=6)
        tp.backup_topics(self.world.ctx)
        with self.assertRaises(AppError) as confirm:
            tp.restore_topics(self.world.ctx, latest=True, confirmed=False)
        self.assertEqual(confirm.exception.code, "CONFIRMATION_REQUIRED")
        self.assertIn("바뀝니다", confirm.exception.slots["항목"], "되돌리면 무엇이 바뀌는지는 세부(화면에 안 나온다)가 아니라 문구에 있다")


class BlogFolderAndSeedNoteTest(unittest.TestCase):
    def test_a_blog_folder_that_does_not_exist_is_reported_as_not_connected_for_the_three_file_channels(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = World(tmp)
            shutil.rmtree(world.repo)                                                    # 연결해 둔 블로그 폴더가 없어졌다
            self.assertFalse(world.repo.exists())
            states = {item.channel: item.state for item in tp.read_blog_history(world.ctx).channels}
            for channel in ("github_pages", "blogger_en", "blogger_ko"):
                self.assertEqual(states[channel], "not_connected", channel)
            world.repo.mkdir()
            states = {item.channel: item.state for item in tp.read_blog_history(world.ctx).channels}
            self.assertEqual(states["github_pages"], "missing", "폴더가 있으면 '연결 안 됨' 이 아니라 '파일 없음'")

    def test_a_plan_without_any_seed_says_so_and_a_plan_with_seeds_does_not(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = World(tmp, with_world=False)
            self.assertTrue(any("씨앗이 하나도 없습니다" in note for note in world.plan(target=3).notes), "씨앗 파일이 없을 때")
            put(world.paths.seeds, seeds.seeds_to_dict([]))
            self.assertTrue(any("씨앗이 하나도 없습니다" in note for note in world.plan(target=3).notes), "씨앗 파일이 비어 있을 때")
            world.write_world()
            self.assertFalse(any("씨앗이 하나도 없습니다" in note for note in world.plan(target=3).notes))

    def test_a_seeds_file_saved_with_a_utf8_bom_is_read_and_utf16_gets_the_encoding_hint(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = World(tmp)
            original = world.paths.seeds.read_bytes()
            world.paths.seeds.write_bytes(b"\xef\xbb\xbf" + original)
            good = tp.check_files(world.ctx, today=TODAY)
            self.assertTrue(good.ok)
            self.assertEqual(good.seeds, 3)
            world.paths.seeds.write_bytes(original.decode("utf-8").encode("utf-16"))
            bad = next(item for item in tp.check_files(world.ctx, today=TODAY).files if item.name == layout.SEEDS_FILE)
            self.assertEqual(bad.state, "invalid")
            self.assertIn("UTF-8", bad.reason, "안내에 '메모장 → UTF-8' 한 줄")


class CrossChannelSpreadTest(unittest.TestCase):
    """채널 사이 같은 주제 검사(R-149 E) — 이번 실행에서 만든 후보끼리만 보고 걸린 것을 **표시만** 한다(후보를 지우거나 막지 않는다, D-74)."""

    def test_the_same_source_topic_in_two_channels_is_noted_and_a_different_one_or_one_channel_is_not(self):
        first = ts.rated(70, candidate_id="cand0001", channel="naver_a", source_topic_id="src-same", topic="예시 같은 주제 글")
        second = ts.rated(70, candidate_id="cand0002", channel="naver_b", source_topic_id="src-same", topic="예시 같은 주제 글")
        other = ts.rated(70, candidate_id="cand0003", channel="naver_b", source_topic_id="src-other", topic="예시 다른 주제 글")
        notes = tp._spread_notes([SimpleNamespace(candidates=(first,)), SimpleNamespace(candidates=(second,))])
        self.assertTrue(notes)
        self.assertTrue(all(line.startswith("채널 사이 같은 주제: ") for line in notes))
        self.assertTrue(any("네이버 A" in line and "네이버 B" in line for line in notes), notes)
        self.assertEqual(tp._spread_notes([SimpleNamespace(candidates=(first,)), SimpleNamespace(candidates=(other,))]), (), "원천 주제가 다르면 걸리지 않는다")
        self.assertEqual(tp._spread_notes([SimpleNamespace(candidates=(first, ts.rated(70, candidate_id="cand0004", channel="naver_a", source_topic_id="src-same", topic="예시 같은 주제 글 둘")))]), (), "한 채널뿐이면 견주지 않는다")

    def test_a_plan_shows_the_spread_notes_but_removes_no_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = World(tmp)
            plain = world.plan(target=6)
            fake = (SimpleNamespace(problems=("네이버 A 과 네이버 B 의 후보는 일곱 항목 중 1개만 달라 충분하지 않습니다(최소 4개)",)),)
            with mock.patch.object(tp.dedupe, "check_topic_spread", return_value=fake):
                noted = world.plan(target=6)
                saved = world.generate(target=6)
            self.assertTrue(any(note.startswith("채널 사이 같은 주제: ") for note in noted.notes))
            self.assertTrue(any(note.startswith("채널 사이 같은 주제: ") for note in saved.notes), "저장했을 때도 같은 표시")
            self.assertEqual((noted.total, saved.total), (plain.total, plain.total), "표시만 한다 — 후보 수가 같다")


class SafetyAndNoticeTest(unittest.TestCase):
    def test_every_notice_of_a_plan_is_a_clean_six_key_card_and_the_stop_count_is_a_calculation(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = World(tmp)
            result = world.plan(target=6)
            cards = [item for plan in result.plans for item in plan.notices]
            self.assertTrue(cards)
            for item in cards:
                self.assertIsInstance(item, notice.Notice)
                self.assertEqual(sorted(item.to_dict()), ["action", "code", "details", "level", "message", "title"])
                for text in (item.title, item.message, item.action, *item.details):
                    self.assertTrue(notice.is_clean(text), text)
            self.assertTrue(all(isinstance(plan.stopped, int) and plan.stopped == 0 for plan in result.plans))
            with mock.patch.object(tp, "safety", SimpleNamespace(assess=lambda candidate: SimpleNamespace(stop=True))):          # 서비스가 부르는 이름만 바꾼다(생성기는 진짜 안전 표시를 쓴다)
                stopped = world.plan(target=6)
            self.assertEqual([plan.stopped for plan in stopped.plans], [len(plan.candidates) for plan in stopped.plans], "저장하지 않고 assess(후보).stop 으로 센다")
            world.generate(target=6)
            with open_read_only(world.paths.database) as store:
                self.assertTrue(all("stop" not in key for key in store.list_candidates()[0].to_dict()), "자동 초안 중지는 저장하지 않는다")

    def test_the_campaign_list_is_empty_in_p3_and_the_service_creates_no_campaign_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = World(tmp)
            with mock.patch.object(tp.gen, "generate", wraps=tp.gen.generate) as spy:
                world.generate(target=4)
            self.assertTrue(spy.called)
            for call in spy.call_args_list:
                self.assertEqual(tuple(call.kwargs["campaigns"]), ())
            self.assertEqual(sorted(os.listdir(world.paths.folder)), ["calendar.json", "seeds.json", "topic_engine.db"])
            self.assertFalse(any("campaign" in name.lower() for name in os.listdir(world.paths.folder)), "협찬 정보 파일은 P6 에서 만든다")


class CheckStatusTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.world = World(self.tmp.name)

    def test_check_reads_strictly_and_reports_an_invalid_file_with_a_clean_reason_without_touching_it(self):
        good = tp.check_files(self.world.ctx, today=TODAY)
        self.assertTrue(good.ok)
        self.assertEqual((good.seeds, good.entries), (3, 1))
        self.assertEqual(len(good.proposals), 3, "180일 넘게 선택 안 한 씨앗은 제안만 한다")
        self.assertEqual(len(good.evaluations), 1)
        self.world.paths.seeds.write_text('{"schema": 1, "seeds": [{"seed_id": "x"}]}', encoding="utf-8")
        before = self.world.paths.seeds.read_bytes()
        bad = tp.check_files(self.world.ctx, today=TODAY)
        self.assertFalse(bad.ok)
        item = next(entry for entry in bad.files if entry.name == layout.SEEDS_FILE)
        self.assertEqual(item.state, "invalid")
        self.assertTrue(item.reason and notice.is_clean(item.reason), item.reason)
        self.assertEqual(self.world.paths.seeds.read_bytes(), before)
        self.world.paths.seeds.write_bytes(b"{broken")
        broken = next(entry for entry in tp.check_files(self.world.ctx, today=TODAY).files if entry.name == layout.SEEDS_FILE)
        self.assertEqual((broken.state, broken.reason), ("invalid", "글자나 JSON 모양이 올바르지 않습니다(메모장이라면 '다른 이름으로 저장' 에서 인코딩을 UTF-8 로 저장했는지, 쉼표·따옴표가 맞는지 확인해 주세요)"))

    def test_the_calendar_lines_do_not_depend_on_the_order_of_the_entries_in_the_file(self):
        base = json.loads(self.world.paths.calendar.read_text(encoding="utf-8"))
        entry = base["entries"][0]
        base["entries"] = [dict(entry, entry_id=f"cal-{number}", name=f"예시 시기 {name}") for number, name in enumerate(("다", "가", "나"))]
        put(self.world.paths.calendar, base)
        first = tp.check_files(self.world.ctx, today=TODAY).evaluations
        base["entries"].reverse()
        put(self.world.paths.calendar, base)
        second = tp.check_files(self.world.ctx, today=TODAY).evaluations
        self.assertEqual(len(first), 3)
        self.assertEqual(first, second, "같은 입력은 파일 순서와 무관하게 같은 결과(결정성)")
        self.assertEqual(list(first), sorted(first))

    def test_a_brand_only_seed_is_previewed_as_needs_topic_without_saving_anything(self):
        pool = [dataclasses.replace(ts.example_seed(seed_id="b1", keyword="Gemini"), major="가", minor="없는 분류")]
        put(self.world.paths.seeds, seeds.seeds_to_dict(pool))
        before = tree(self.tmp.name)
        result = tp.check_files(self.world.ctx, today=TODAY)
        self.assertTrue(result.notices)
        self.assertTrue(all(item.code in ("BRAND_ONLY", "BRAND_SPECIFIED", "BRAND_UNFEASIBLE") for item in result.notices))
        self.assertTrue(all(any("Gemini" in line for line in item.details) for item in result.notices))
        self.assertEqual({item.details[0].split(" · ")[0] for item in result.notices}, {"네이버 A", "네이버 B"}, "후보 생성이 꺼진 채널(GitHub Pages·Blogger)은 미리 보지 않는다")
        self.assertEqual(tree(self.tmp.name), before)

    def test_status_reports_every_state_of_the_store_and_files_without_raising(self):
        self.assertEqual(tp.status(self.world.ctx).store_state, "missing")
        self.world.generate(target=4)
        ready = tp.status(self.world.ctx)
        self.assertEqual((ready.store_state, ready.store_version), ("ready", 1))
        self.assertEqual(dict(ready.counts)["naver_a"] + dict(ready.counts)["naver_b"], len(self.world.stored()))
        self.assertEqual(ready.enabled, ("naver_a", "naver_b"))
        self.assertEqual(next(item for item in ready.files if item.name == layout.SEEDS_FILE).count, 3)
        database = self.world.paths.database
        good = database.read_bytes()
        database.write_bytes(os.urandom(4096))
        self.assertEqual(tp.status(self.world.ctx).store_state, "corrupt")
        database.write_bytes(good)
        connection = sqlite3.connect(str(database))
        with connection:
            connection.execute("PRAGMA user_version = 9")
        connection.close()
        self.assertEqual(tp.status(self.world.ctx).store_state, "newer")
        self.assertEqual(code_of(tp.plan_candidates, self.world.ctx, today=TODAY), "TOPIC_STORE_VERSION_UNSUPPORTED", "후보를 읽을 수 없으면 비었다고 가정하지 않고 멈춘다")
        self.world.paths.profiles.write_text("{broken", encoding="utf-8")
        invalid = next(item for item in tp.status(self.world.ctx).files if item.name == layout.CHANNEL_PROFILES_FILE)
        self.assertEqual(invalid.state, "invalid")


class ListShowTopReviewTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.world = World(self.tmp.name)
        self.created = "2026-11-10T00:00:00Z"
        self.expiry = "2027-02-08T00:00:00Z"

    def add(self, *items):
        with open_for_write(self.world.paths.database) as store:
            store.add_candidates(lambda existing: list(items), now="2026-11-10T01:00:00Z")

    def cand(self, suffix, final=70, **more):
        values = {"candidate_id": f"tc-naver_a-seed-aaaa00000000{suffix}", "channel": "naver_a", "cluster": "local-ai", "topic": f"예시 주제 {suffix}번 글", "created_at": self.created}
        values.update(more)
        return ts.rated(final, **values)

    def test_list_numbers_by_creation_order_and_filters_keep_the_numbers(self):
        self.add(self.cand("0001", 85), self.cand("0002", 70, channel="naver_b"), self.cand("0003", 40), self.cand("0004", 60, review_expires_at=self.expiry))
        everything = tp.list_candidates(self.world.ctx)
        self.assertEqual([row.ordinal for row in everything.rows], [1, 2, 3, 4])
        self.assertEqual((everything.total, everything.store_state), (4, "ready"))
        only_b = tp.list_candidates(self.world.ctx, channel="naver_b")
        self.assertEqual([(row.ordinal, row.candidate.channel) for row in only_b.rows], [(2, "naver_b")], "거르면 순번에 빈 곳이 생긴다")
        self.assertEqual([row.ordinal for row in tp.list_candidates(self.world.ctx, band="HOLD").rows], [4])
        self.assertEqual([row.ordinal for row in tp.list_candidates(self.world.ctx, status="NEW").rows], [1, 2, 3, 4])
        self.assertEqual(tp.list_candidates(self.world.ctx, status="REJECTED").rows, ())
        data = everything.to_dict()
        self.assertEqual((data["total"], data["shown"], data["candidates"][0]["ordinal"], len(data["candidates"][0]["ref"])), (4, 4, 1, 8))

    def test_show_resolves_by_ordinal_by_full_number_and_by_a_hex_prefix(self):
        self.add(self.cand("0001", 85), self.cand("0002", 70), self.cand("beef", 60, review_expires_at=self.expiry))
        self.assertEqual(tp.show_candidate(self.world.ctx, "3").row.candidate.candidate_id, "tc-naver_a-seed-aaaa00000000beef")
        self.assertEqual(tp.show_candidate(self.world.ctx, "tc-naver_a-seed-aaaa000000000001").row.ordinal, 1)
        self.assertEqual(tp.show_candidate(self.world.ctx, "aaaa00000000be").row.ordinal, 3)
        self.assertEqual(tp.show_candidate(self.world.ctx, "AAAA00000000BE").row.ordinal, 3, "대문자도 받는다")
        self.assertEqual(code_of(tp.show_candidate, self.world.ctx, "aaaa"), "TOPIC_CANDIDATE_AMBIGUOUS", "앞 4자가 셋과 맞는다")
        self.assertEqual(code_of(tp.show_candidate, self.world.ctx, "aaaa00000000000"), "TOPIC_CANDIDATE_AMBIGUOUS")
        self.assertEqual(code_of(tp.show_candidate, self.world.ctx, "4"), "TOPIC_CANDIDATE_NOT_FOUND")
        self.assertEqual(code_of(tp.show_candidate, self.world.ctx, "dead"), "TOPIC_CANDIDATE_NOT_FOUND")
        self.assertEqual(code_of(tp.show_candidate, self.world.ctx, "aa"), "TOPIC_CANDIDATE_NOT_FOUND", "너무 짧은 앞부분")
        self.assertEqual(code_of(tp.show_candidate, self.world.ctx, ""), "TOPIC_CANDIDATE_NOT_FOUND")
        for typed in (KEY_LIKE, "zzzzzz", "한글 번호", "1" * 12):
            with self.subTest(typed=typed[:10]):
                with self.assertRaises(AppError) as caught:
                    tp.show_candidate(self.world.ctx, typed)
                self.assertEqual(caught.exception.code, "TOPIC_CANDIDATE_NOT_FOUND")
                self.assertNotIn(typed, str(caught.exception.slots), "번호 모양이 아닌 글은 되풀이하지 않는다")

    def test_show_carries_the_safety_notices_the_hold_stay_and_the_snapshot_count(self):
        self.add(self.cand("0001", 60, review_expires_at=self.expiry))
        shown = tp.show_candidate(self.world.ctx, "1")
        self.assertEqual([item.code for item in shown.notices], ["HOLD_BAND"])
        self.assertEqual((shown.stay.expires_at, shown.snapshots, shown.link, shown.row.stop), (self.expiry, 1, None, False))
        data = shown.to_dict()
        self.assertEqual((data["hold"]["entered_at"], data["score_snapshots"], data["link"]), (self.created, 1, None))
        with open_for_write(self.world.paths.database) as store:
            store.save_link(CandidateLink.of(store.list_candidates()[0], legacy_candidate_id="legacy-1"), now="2026-11-10T02:00:00Z")
        self.assertEqual(tp.show_candidate(self.world.ctx, "1").link.legacy_candidate_id, "legacy-1")

    def test_top_picks_recommended_then_general_hides_rejected_and_says_how_many_qualified(self):
        self.add(self.cand("0001", 90), self.cand("0002", 82), self.cand("0003", 70), self.cand("0004", 66), self.cand("0005", 64, review_expires_at=self.expiry),
                 self.cand("0006", 95, work_status="REJECTED"), self.cand("0007", 88, channel="naver_b"))
        result = tp.top_candidates(self.world.ctx)
        by = {item.channel: item for item in result.channels}
        self.assertEqual([row.candidate.candidate_id[-4:] for row in by["naver_a"].rows], ["0001", "0002", "0003", "0004"][:len(by["naver_a"].rows)])
        self.assertEqual(len(by["naver_a"].rows), 2, "같은 주제 묶음은 최대 2개")
        self.assertEqual((by["naver_a"].shortfall, by["naver_b"].shortfall, len(by["naver_b"].rows)), (3, 4, 1))
        self.assertEqual((by["github_pages"].enabled, by["github_pages"].rows), (False, ()))
        self.assertNotIn("0006", [row.candidate.candidate_id[-4:] for row in by["naver_a"].rows], "사람이 제외한 후보는 점수가 높아도 올리지 않는다")
        self.assertEqual(tp.top_candidates(self.world.ctx, channel="naver_b").channels[0].channel, "naver_b")
        self.assertEqual(len(tp.top_candidates(self.world.ctx, channel="naver_b").channels), 1)

    def test_top_leaves_out_a_candidate_whose_stored_score_does_not_match_the_channel_weights_and_says_so(self):
        off = ts.make(candidate_id="tc-naver_a-seed-aaaa000000000009", channel="naver_a", language="ko", topic="예시 점수가 어긋난 글", topic_cluster="local-ai", created_at=self.created,
                      scores=ts.card(75, channel_fit=60, feasibility=80, differentiation=60, timing=80, evidence=60, monetization=80))
        self.add(self.cand("0001", 90), off)
        row = next(item for item in tp.top_candidates(self.world.ctx).channels if item.channel == "naver_a")
        self.assertEqual([entry.candidate.candidate_id[-4:] for entry in row.rows], ["0001"])
        self.assertEqual(len(row.problems), 1)
        self.assertTrue(notice.is_clean(row.problems[0]), row.problems[0])

    def test_review_lists_the_holds_with_deadlines_and_marks_the_expired_ones_without_deleting(self):
        self.add(self.cand("0001", 60, review_expires_at=self.expiry), self.cand("0002", 56, review_expires_at="2026-12-01T00:00:00Z"), self.cand("0003", 70, work_status="HOLD"), self.cand("0004", 85))
        early = tp.review_holds(self.world.ctx, today="2026-11-20")
        self.assertEqual([(item.row.ordinal, item.expired, item.days_left) for item in early.items], [(2, False, 11), (1, False, 80), (3, False, None)])
        self.assertEqual(early.expired, 0)
        late = tp.review_holds(self.world.ctx, today="2027-03-01")
        self.assertEqual([(item.row.ordinal, item.expired) for item in late.items], [(2, True), (1, True), (3, False)])
        self.assertEqual(late.expired, 2)
        self.assertEqual(len(self.world.stored()), 4, "기한이 지나도 지우지 않는다")
        exact = tp.review_holds(self.world.ctx, today="2026-12-01")
        self.assertTrue(next(item for item in exact.items if item.row.ordinal == 2).expired, "기한 날 0시 정각이면 지난 것이다")
        self.assertEqual(tp.review_holds(self.world.ctx, today=TODAY).to_dict()["expired"], 0)

    def test_an_old_structure_store_is_reported_not_read(self):
        class V2(TopicStore):
            SCHEMA_VERSION = 2
            SHAPES = {**TopicStore.SHAPES, 2: TopicStore.SHAPES[1]}
            MIGRATIONS = {1: lambda db: None}

        self.add(self.cand("0001", 85))
        with mock.patch.object(tp, "open_read_only", lambda path: V2.open(path, migrate=False)):
            self.assertEqual(tp.list_candidates(self.world.ctx).store_state, "old_structure")
            self.assertEqual(tp.list_candidates(self.world.ctx).rows, ())
            self.assertEqual(tp.review_holds(self.world.ctx, today=TODAY).store_state, "old_structure")
            self.assertEqual(code_of(tp.show_candidate, self.world.ctx, "1"), "TOPIC_CANDIDATE_NOT_FOUND")


class ServiceBackupTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.world = World(self.tmp.name)
        self.world.generate(target=4)

    def test_backup_goes_to_its_own_folder_and_the_old_backup_command_is_not_involved(self):
        old = projects.backup_store(self.world.ctx)
        result = tp.backup_topics(self.world.ctx)
        self.assertEqual(result.path.parent, self.world.ctx.workspace.backups_dir / "topic_engine")
        self.assertTrue(old.parent == self.world.ctx.workspace.backups_dir and old.name.startswith("chanceblog-"))
        self.assertEqual([item.name for item in projects.list_backups(self.world.ctx)], [old.name], "기존 backup 목록에 주제 엔진 백업이 섞이지 않는다")
        self.assertEqual((result.files, result.missing), ((layout.SEEDS_FILE, layout.CALENDAR_FILE, layout.ENGINE_DB_FILE), (layout.CHANNEL_PROFILES_FILE,)))

    def test_the_backup_has_no_key_not_even_one_put_in_the_key_store(self):
        keystore = self.world.ctx.get_keystore()
        keystore.put("image_unsplash:test1", {"access_key": KEY_LIKE})
        result = tp.backup_topics(self.world.ctx)
        for path in result.path.iterdir():
            self.assertNotIn(KEY_LIKE.encode(), path.read_bytes(), path.name)

    def test_restore_checks_the_backup_first_asks_for_confirmation_and_then_restores(self):
        result = tp.backup_topics(self.world.ctx)
        before = len(self.world.stored())
        self.world.generate(target=8)
        grown = len(self.world.stored())
        live = {path.name: digest(path) for path in self.world.paths.folder.iterdir() if path.is_file()}
        for flag in (None, False, 1, "yes"):
            with self.subTest(flag=flag):
                self.assertEqual(code_of(tp.restore_topics, self.world.ctx, result.path.name, confirmed=flag), "CONFIRMATION_REQUIRED")
        self.assertEqual({path.name: digest(path) for path in self.world.paths.folder.iterdir() if path.is_file()}, live, "확인이 없으면 아무것도 바뀌지 않는다")
        restored = tp.restore_topics(self.world.ctx, latest=True, confirmed=True)
        self.assertEqual(len(self.world.stored()), before)
        self.assertGreaterEqual(grown, before)
        self.assertIsNotNone(restored.safety)
        with open_read_only(restored.safety / layout.ENGINE_DB_FILE) as store:
            self.assertEqual(store.count(), grown, "바꾸기 직전 상태가 안전 백업에 있다")

    def test_a_bad_backup_is_refused_even_without_confirmation(self):
        result = tp.backup_topics(self.world.ctx)
        (result.path / layout.SEEDS_FILE).write_bytes(b"changed")
        self.assertEqual(code_of(tp.restore_topics, self.world.ctx, result.path.name, confirmed=False), "TOPIC_BACKUP_INVALID")
        self.assertEqual(code_of(tp.restore_topics, self.world.ctx, "topic-20200101-000000", confirmed=True), "TOPIC_BACKUP_INVALID")
        self.assertEqual(code_of(tp.restore_topics, self.world.ctx, confirmed=True), "TOPIC_BACKUP_INVALID", "백업 이름도 --latest 도 없다")


class DraftStatesTest(unittest.TestCase):
    """글 상태(DRAFTING·DRAFT_READY)의 입력 방법 — 연결에 기존 후보 번호가 있으면 이은 글의 그 채널 흐름 상태에서 읽는다(저장하지 않는다)."""

    def ctx_with(self, legacy, projects):
        class FakeStore:                                              # 읽기 전용으로 연 글 보관함의 가짜 — 후보와 글을 번호로 찾아 준다
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def load_candidate(self, key):
                if key not in legacy:
                    raise AppError("CANDIDATE_NOT_FOUND", {"항목": key})
                return legacy[key]

            def load(self, key):
                if key not in projects:
                    raise AppError("CONTENT_NOT_FOUND", {"항목": key})
                return projects[key]

        return SimpleNamespace(reading_only=lambda: SimpleNamespace(store=FakeStore))

    def link(self, engine, legacy):
        return CandidateLink(engine_candidate_id=engine, legacy_candidate_id=legacy, draft_plan_id=None, source_topic_id=None, seed_id=None, channel="naver_a")

    def test_only_the_two_draft_flow_states_count_and_unreadable_ones_are_noted(self):
        from chanceblog_desktop.content import status as st
        project = lambda state: SimpleNamespace(variants={"naver_a": SimpleNamespace(status=state)})                 # noqa: E731
        ctx = self.ctx_with({"L1": SimpleNamespace(project_id="P1"), "L2": SimpleNamespace(project_id="P2"), "L3": SimpleNamespace(project_id="P3"), "L4": SimpleNamespace(project_id=None), "L5": SimpleNamespace(project_id="P9")},
                            {"P1": project(st.DRAFT_GENERATED), "P2": project(st.READY_TO_COPY), "P3": project(st.PUBLISHED_MANUAL)})
        links = [self.link("e1", "L1"), self.link("e2", "L2"), self.link("e3", "L3"), self.link("e4", "L4"), self.link("e5", "L5"), self.link("e6", "L-none"), self.link("e7", None)]
        states, notes = tp._draft_states(ctx, links)
        self.assertEqual(states, {"e1": slots.DRAFTING, "e2": slots.DRAFT_READY})
        self.assertEqual(len(notes), 1, "읽을 수 없는 연결이 있다는 안내 한 줄")
        self.assertTrue(notice.is_clean(notes[0]))
        self.assertEqual(tp._draft_states(ctx, [self.link("e7", None)]), ({}, ()), "기존 후보와 이어지지 않은 연결은 보지 않는다")
        self.assertEqual(tp._draft_states(ctx, []), ({}, ()))

    def test_an_unopenable_old_store_gives_no_states_and_one_note(self):
        def broken():
            raise AppError("STORE_CORRUPT", {"파일": "chanceblog.db"})

        ctx = SimpleNamespace(reading_only=lambda: SimpleNamespace(store=broken))
        states, notes = tp._draft_states(ctx, [self.link("e1", "L1")])
        self.assertEqual((states, len(notes)), ({}, 1))


if __name__ == "__main__":
    unittest.main()
