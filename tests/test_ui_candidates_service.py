"""주제 후보 화면의 실제 공급자(`ui/candidates_adapter.py`) 시험 — 실제 임시 폴더의 엔진 보관함·설정 파일과 진짜 서비스 함수로 읽기·미리 보기·후보 만들기를 해 본다(PySide6 없이 돈다 — CI 와 같은 조건). 네트워크·실제 시계·자격 증명 보관소는 쓰지 않는다.

지키는 것:
  1) **읽기 전용 증명**: 화면이 후보를 읽고 미리 보고 거르고 찾고 고르고 상세를 열어도(보관함 없음·0바이트·옛 구조·정상 600개·깨진 파일·더 새 판·설정 파일 깨짐 모두) 임시 폴더 전체 바이트·파일 목록이 그대로다. 보관함이 없을 때 만들어지지 않는다.
  2) 후보 읽기: 보관함 상태(없음·비어 있음·옛 구조·정상)와 읽기 오류가 쉬운 문장이고, **점수가 그 채널 가중치로 다시 계산한 값과 다른 후보는 홈의 `top_candidates` 와 같은 규칙으로 빼고** 개수만 알린다. 홈의 추천 줄과 이 화면의 카드는 같은 점수·같은 구간이다.
  3) 후보 만들기: 확인창 전에는 0쓰기·취소하면 0쓰기·`만들기` 에서만 서비스 `generate_candidates(confirmed=True, trend=None)` 한 번. 보관함이 없으면 보관함 파일 하나만 만들고(설정 파일 셋은 안 만든다) 옛 구조는 사본을 남기고 올린다. **후보는 지워지지 않고 더해진다.**
  4) 실패(다른 창이 씀·읽기 전용·깨진 보관함)는 종류별 쉬운 문장이고 보관함은 쓰기 전 상태 그대로(바이트 같음)이며 목록이 안 바뀐다.
  5) 관심도 공급자는 `None`(네트워크 호출 0)이고 키·자격 증명 저장소를 부르지 않는다. 쓰는 길은 어댑터의 서비스 함수 하나뿐이다(소스 시험).
"""
import ast
import dataclasses
import hashlib
import json
import os
import socket
import sqlite3
import stat
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import service_support as ss  # noqa: E402
import topics_support as ts  # noqa: E402
from test_topicdb_store import v1_class  # noqa: E402

from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.service import topic_files as tf  # noqa: E402
from chanceblog_desktop.service import topics as topic_service  # noqa: E402
from chanceblog_desktop.topicdb import store as topic_store  # noqa: E402
from chanceblog_desktop.topics import channels as ch  # noqa: E402
from chanceblog_desktop.topics import hold as holdmod  # noqa: E402
from chanceblog_desktop.topics import score as scoremod  # noqa: E402
from chanceblog_desktop.topics import seeds as sd  # noqa: E402
from chanceblog_desktop.topics.model import check_candidate_score  # noqa: E402
from chanceblog_desktop.ui import adapters, candidates_adapter  # noqa: E402
from chanceblog_desktop.ui.core import app_state, candidates as cd, candidates_view as cv, gauges, jobs, services, text  # noqa: E402

UI_DIR = ROOT / "src" / "chanceblog_desktop" / "ui"
T = text.T
SAFE = lambda *a: None  # noqa: E731
NEVER = lambda: False  # noqa: E731
STAMP = "2026-11-01T00:00:00Z"
KEY_SHAPED = "AK" + "IA" + "ABCDEFGHIJKLMNOP"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class World:
    """임시 데이터 폴더(가짜 블로그 저장소 포함)와 진짜 어댑터. `seeds` 는 Seed 목록(없으면 설정 파일을 만들지 않는다)."""

    def __init__(self, test, *, seeds=None):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        test.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.ctx = ss.make_ctx(tmp.name)
        self.paths = tf.topic_paths(self.ctx.workspace)
        self.provider = candidates_adapter.ServiceCandidatesProvider(context_factory=lambda data_dir=None: self.ctx)
        if seeds is not None:
            self.paths.folder.mkdir(parents=True, exist_ok=True)
            self.paths.seeds.write_bytes((json.dumps(sd.seeds_to_dict(seeds), ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"))

    def controller(self):
        return cv.CandidatesController(self.provider, jobs.JobRunner())

    def tree(self):
        return ss.tree_snapshot(self.tmp)

    def listing(self):
        return sorted(str(path.relative_to(self.tmp)) for path in self.tmp.rglob("*") if ".git" not in path.relative_to(self.tmp).parts)

    def add(self, *candidates, store_class=topic_store.TopicStore):
        with store_class.open(self.paths.database) as store:
            store.add_candidates(lambda existing: tuple(candidates), now=STAMP)

    def stored(self):
        with topic_store.open_read_only(self.paths.database) as store:
            return store.list_candidates()


def approved_seeds(count=12):
    return [ts.example_seed(seed_id=f"g{number}", keyword=f"예시 낱말 {number}", major="가전", minor="소형가전", target_type="product") for number in range(1, count + 1)]


def candidate(number, final, channel="naver_a", **more):
    """점수가 `final` 인 예시 후보 — 주제 묶음·씨앗 번호·관점이 모두 달라 서로 '같은 후보' 로 묶이지 않는다(남은 자리를 세는 시험이 늘 정확히 센다)."""
    band = scoremod.band_of(final)
    values = dict(cluster=f"c-{number}", seed_id=f"s{number}", topic_angle=f"angle-{number}", review_expires_at=holdmod.expiry_for(band, ts.STAMP), topic=f"예시 후보 {number:03d}", primary_keyword=f"예시 낱말 {number:03d}")
    values.update(more)
    return ts.rated(final, candidate_id=f"tc-{channel}-seed-{number:016x}", channel=channel, **values)


def load(controller):
    data = controller.provider.load_candidates(SAFE, NEVER)
    controller.apply_loaded(data)
    return data


def drive(controller, starter):
    results = {}
    status, job = starter(on_done=lambda result, _payload: results.setdefault("ok", result), on_error=lambda failure, _payload: results.setdefault("failed", failure))
    if status != "started":
        return status, None
    job.join(30)
    if "ok" in results:
        controller.apply_write_ok(results["ok"])
        return status, "ok"
    controller.apply_write_failed(results["failed"])
    return status, "failed"


# ---- 1) 읽기 전용 증명 ---------------------------------------------------------------------------------------------------------------
class ReadOnlyTest(unittest.TestCase):
    def use(self, controller):
        """화면이 하는 읽기 일을 모두 해 본다 — 읽기·거르기·찾기·고르기·상세·창 방식 바꾸기·미리 보기."""
        load(controller)
        for call in (lambda: controller.set_channel("naver_a"), lambda: controller.set_status("NEW"), lambda: controller.set_band("high"), lambda: controller.set_query("예시 낱말"), controller.reset_filters, controller.toggle_more_filters,
                     controller.show_more, lambda: controller.set_layout("drawer"), lambda: controller.set_layout("fixed")):
            call()
            controller.view()
        for row in controller.rows()[:3]:
            controller.select(row.candidate.candidate_id)
            controller.detail_view()
        controller.close_detail()
        drive(controller, controller.start_preview)
        controller.view()
        controller.make_dialog()
        controller.discard_make()
        controller.close_preview()

    def test_a_data_folder_without_the_engine_folder_is_read_and_previewed_without_creating_anything(self):
        world = World(self)
        before, listing = world.tree(), world.listing()
        controller = world.controller()
        self.use(controller)
        self.assertEqual((controller.state, controller.data.store, controller.view()["grid"]["empty"]["kind"]), ("normal", "missing", "nostore"))
        self.assertEqual(world.tree(), before)
        self.assertEqual(world.listing(), listing)
        self.assertFalse(world.paths.folder.exists(), "읽기·미리 보기는 보관함 폴더를 만들지 않는다")

    def test_a_ready_store_with_six_hundred_candidates_is_read_and_used_without_touching_a_single_byte(self):
        world = World(self, seeds=approved_seeds())
        world.add(*(candidate(number, (number * 7) % 101, ("naver_a", "naver_b", "blogger_ko", "blogger_en", "github_pages")[number % 5]) for number in range(1, 601)))
        before, listing = world.tree(), world.listing()
        controller = world.controller()
        started = time.time()
        load(controller)
        view = controller.view()
        self.assertEqual((len(view["grid"]["cards"]), view["grid"]["found"]), (24, 600), "수백 개여도 카드는 한 번에 24장")
        self.use(controller)
        self.assertEqual(world.tree(), before)
        self.assertEqual(world.listing(), listing)
        self.assertEqual((controller.data.store, len(controller.rows()), controller.data.total), ("ready", 600, 600))
        self.assertLess(time.time() - started, 60)

    def test_an_empty_file_an_old_structure_a_newer_structure_and_broken_files_are_read_as_easy_states_and_never_touched(self):
        cases = {}
        world = World(self)
        world.paths.folder.mkdir(parents=True)
        world.paths.database.write_bytes(b"")
        cases["empty"] = world
        world = World(self)
        world.add(candidate(1, 80), store_class=v1_class())
        cases["old"] = world
        for name, content in (("newer", None), ("corrupt", b"this is not a database at all, just text" * 40)):
            world = World(self)
            if content is None:
                world.add(candidate(1, 80))
                with sqlite3.connect(str(world.paths.database), isolation_level=None) as connection:
                    connection.execute("PRAGMA user_version = 9")
                connection.close()
            else:
                world.paths.folder.mkdir(parents=True)
                world.paths.database.write_bytes(content)
            cases[name] = world
        for name, world in cases.items():
            before, listing = world.tree(), world.listing()
            with self.subTest(case=name):
                if name in ("empty", "old"):
                    data = world.provider.load_candidates(SAFE, NEVER)
                    self.assertEqual((data.store, data.rows), ({"empty": "empty", "old": "old_structure"}[name], ()))
                    controller = world.controller()
                    controller.apply_loaded(data)
                    self.assertEqual(controller.view()["grid"]["empty"]["kind"], {"empty": "nostore", "old": "old"}[name])
                else:
                    with self.assertRaises(cd.CandidateFailure) as caught:
                        world.provider.load_candidates(SAFE, NEVER)
                    expected = {"newer": ("newer", T["board_err_newer"]), "corrupt": ("corrupt", T["board_err_store"])}[name]
                    self.assertEqual((caught.exception.kind, caught.exception.user_message), expected)
                    controller = world.controller()
                    controller.apply_load_failed(caught.exception)
                    self.assertEqual(controller.view()["state"], "error")
                    self.assertFalse(controller.view()["make"]["enabled"], "읽지 못한 보관함 위에는 만들기가 꺼져 있다")
                self.assertEqual(world.tree(), before)
                self.assertEqual(world.listing(), listing)

    def test_a_broken_setting_file_is_an_easy_error_and_is_never_overwritten(self):
        world = World(self)
        world.paths.folder.mkdir(parents=True)
        world.paths.profiles.write_bytes(b"{broken")
        before = world.tree()
        with self.assertRaises(cd.CandidateFailure) as caught:
            world.provider.load_candidates(SAFE, NEVER)
        self.assertEqual((caught.exception.kind, caught.exception.user_message), ("invalid", T["board_err_profiles"]))
        with self.assertRaises(cd.CandidateFailure) as again:
            world.provider.preview_make(SAFE, NEVER)
        self.assertEqual(again.exception.kind, "invalid")
        self.assertEqual(world.tree(), before)

    def test_a_data_folder_that_is_missing_is_an_easy_sentence(self):
        provider = candidates_adapter.ServiceCandidatesProvider(str(ROOT / "no-such-folder-for-candidates"))
        for call in (provider.load_candidates, provider.preview_make):
            with self.assertRaises(cd.CandidateFailure) as caught:
                call(SAFE, NEVER)
            self.assertEqual(caught.exception.user_message, T["data_dir_missing"])
        self.assertFalse((ROOT / "no-such-folder-for-candidates").exists())

    def test_an_unreadable_seed_file_does_not_stop_the_candidates_from_being_read(self):
        world = World(self)
        world.add(candidate(1, 80, seed_id="g1"))
        world.paths.seeds.write_bytes(b"{broken")
        before = world.tree()
        data = world.provider.load_candidates(SAFE, NEVER)
        self.assertEqual((len(data.rows), data.seeds), (1, ()))
        controller = world.controller()
        controller.apply_loaded(data)
        controller.select(controller.rows()[0].candidate.candidate_id)
        self.assertEqual(controller.detail_view()["seed"]["rows"][1]["value"], "Seed 정보를 찾지 못했어요")
        self.assertEqual(world.tree(), before)


# ---- 2) 읽기 — 홈과 같은 점수·같은 구간 -----------------------------------------------------------------------------------------------
class ReadTest(unittest.TestCase):
    def test_the_cards_have_the_same_score_band_and_channel_name_as_the_home_recommendation_rows(self):
        world = World(self)
        items = [candidate(number, final, "naver_a" if number % 2 else "naver_b") for number, final in enumerate((95, 91, 88, 84, 82, 80, 79, 75, 70, 66, 65, 61, 58, 50, 49, 20, 0), start=1)]
        world.add(*items)
        home = adapters.ServiceHomeProvider(context_factory=lambda data_dir=None: world.ctx)
        reads = {read.key: read for read in home._channels(world.ctx)}
        controller = world.controller()
        load(controller)
        controller.limit = 100
        cards = {card["title"]: card for card in controller.view()["grid"]["cards"]}
        compared = 0
        for key, read in reads.items():
            for row in read.rows:
                card = cards[row.title]
                with self.subTest(channel=key, title=row.title):
                    self.assertEqual((card["score"], card["ring"]), (row.score, row.score is not None))
                    self.assertEqual(card["band_label"], gauges.score_band(row.score).name, "홈과 같은 구간 이름")
                    self.assertEqual(card["channel"]["name"], read.name, "홈과 같은 표시 이름")
                compared += 1
        self.assertGreaterEqual(compared, 8)
        self.assertEqual(len(cards), 17, "홈이 숨기는 보류·낮은 점수 후보도 이 화면에는 있다(전체 후보를 비교하는 화면)")

    def test_a_candidate_whose_stored_score_is_not_the_weighted_one_is_left_out_like_the_home_does_and_counted(self):
        world = World(self)
        bad = ts.make(candidate_id="tc-naver_a-seed-00000000000000aa", channel="naver_a", language="ko", topic="예시 점수가 어긋난 후보", scores=ts.card(80, channel_fit=10, feasibility=90))
        world.add(candidate(1, 85), bad)
        with self.assertRaises(AppError):
            check_candidate_score(bad, ch.default_profiles()[3])
        controller = world.controller()
        data = load(controller)
        self.assertEqual((len(data.rows), data.skipped, data.total), (1, 1, 2))
        home = adapters.ServiceHomeProvider(context_factory=lambda data_dir=None: world.ctx)
        reads = {read.key: read for read in home._channels(world.ctx)}
        self.assertEqual(reads["A"].skipped, 1, "홈도 같은 후보를 뺀다")
        self.assertEqual([banner for banner in controller.view()["banners"]], [("warning", "점수를 확인할 수 없어 뺀 후보가 1개 있어요.")])
        self.assertNotIn("예시 점수가 어긋난 후보", [card["title"] for card in controller.view()["grid"]["cards"]])

    def test_the_channel_names_the_colors_and_the_weights_come_from_the_channel_profiles(self):
        world = World(self)
        edited = [dataclasses.replace(item, display_name="예시 블로그 라", color_preset="cool_technology") if item.key == "naver_a" else item for item in ch.default_profiles()]
        world.paths.folder.mkdir(parents=True)
        world.paths.profiles.write_bytes((json.dumps(ch.profiles_to_dict(edited), ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
        world.add(candidate(1, 85, "naver_a"))
        data = load(world.controller())
        info = data.channel_map()["naver_a"]
        self.assertEqual((info.name, info.preset, info.enabled), ("예시 블로그 라", "cool_technology", True))
        self.assertEqual(dict(info.weights), {"channel_fit": 25, "feasibility": 15, "differentiation": 10, "timing": 15, "evidence": 10, "monetization": 25})
        self.assertEqual([item.key for item in data.channels], list(ch.CHANNELS))

    def test_the_detail_finds_the_seed_word_from_the_seed_file_and_never_prints_the_seed_number(self):
        world = World(self, seeds=approved_seeds(2))
        world.add(candidate(1, 85, seed_id="g2"))
        controller = world.controller()
        load(controller)
        controller.select(controller.rows()[0].candidate.candidate_id)
        detail = controller.detail_view()
        self.assertEqual(detail["seed"]["rows"][1]["value"], "‘예시 낱말 2’ · 가전 › 소형가전")
        self.assertNotIn("g2", " ".join(item["value"] for item in detail["seed"]["rows"]))

    def test_the_stop_flag_and_the_safety_notices_come_from_the_service_row_and_the_engine(self):
        world = World(self)
        stop = ts.rated(80, candidate_id="tc-naver_a-seed-00000000000000bb", channel="naver_a", topic="예시 영양제 먹으면 바로 낫는 방법", primary_keyword="예시 영양제")
        world.add(stop, candidate(2, 85))
        controller = world.controller()
        data = load(controller)
        self.assertEqual([row.stop for row in data.rows], [True, False])
        cards = {card["title"]: card for card in controller.view()["grid"]["cards"]}
        self.assertEqual([badge["text"] for badge in cards[stop.topic]["badges"]], ["새 후보", "자동 초안 중지"])

    def test_a_key_shaped_stored_text_is_masked_on_the_card_and_in_the_detail(self):
        world = World(self)
        world.add(ts.rated(80, candidate_id="tc-naver_a-seed-00000000000000cc", channel="naver_a", topic="예시 제목 " + KEY_SHAPED, primary_keyword=KEY_SHAPED, selection_reasons=("이유 " + KEY_SHAPED,)))
        controller = world.controller()
        load(controller)
        controller.select(controller.rows()[0].candidate.candidate_id)
        shown = json.dumps([controller.view()["grid"], controller.detail_view()], ensure_ascii=False)
        self.assertNotIn(KEY_SHAPED[:10], shown)
        self.assertIn("가림", shown)

    def test_the_short_number_in_the_detail_is_the_one_the_command_line_shows(self):
        world = World(self)
        world.add(candidate(3, 85))
        controller = world.controller()
        load(controller)
        row = controller.rows()[0]
        controller.select(row.candidate.candidate_id)
        self.assertEqual(controller.detail_view()["number"]["ref"], topic_service.short_ref(row.candidate.candidate_id))


# ---- 3) 미리 보기 ---------------------------------------------------------------------------------------------------------------------
class PreviewTest(unittest.TestCase):
    def test_the_preview_counts_what_the_service_plan_would_make_and_writes_nothing(self):
        world = World(self, seeds=approved_seeds())
        before = world.tree()
        preview = world.provider.preview_make(SAFE, NEVER)
        plan = topic_service.plan_candidates(world.ctx, trend=None)
        self.assertTrue(preview.can_make)
        self.assertEqual(preview.total_new, plan.total)
        self.assertEqual({item.key: item.new for item in preview.channels}, {item.channel: len(item.candidates) for item in plan.plans if item.enabled})
        self.assertEqual([item.key for item in preview.channels], ["naver_a", "naver_b"], "후보 생성이 켜진 채널만")
        self.assertEqual((preview.store, preview.lacks, preview.seeds_proposed), ("missing", (), 0))
        self.assertGreaterEqual(preview.seeds_used, 1)
        self.assertTrue(all(item.remaining == 20 and item.target == 20 for item in preview.channels))
        self.assertEqual(world.tree(), before)

    def test_proposed_seeds_are_never_used_and_the_preview_says_how_many_wait(self):
        world = World(self, seeds=[ts.example_seed(seed_id="p1", keyword="예시 승인 전 하나", state="proposed", major="가전", minor="소형가전", target_type="product"), ts.example_seed(seed_id="p2", keyword="예시 승인 전 둘", state="proposed", major="가전", minor="소형가전", target_type="product")])
        preview = world.provider.preview_make(SAFE, NEVER)
        self.assertEqual((preview.can_make, preview.lacks, preview.seeds_proposed, preview.seeds_used, preview.total_new), (False, ("no_seed",), 2, 0, 0))
        controller = world.controller()
        load(controller)
        drive(controller, controller.start_preview)
        self.assertIsNone(controller.make_dialog())
        prep = controller.view()["prep"]
        self.assertIn("승인한 Seed 가 없어요. Seed 관리에서 Seed 를 승인해 주세요.", prep["lines"])
        self.assertIn("승인 전 Seed 2개는 승인하기 전에는 쓰이지 않아요.", prep["lines"])
        self.assertFalse(world.paths.database.exists(), "승인 전 Seed 만 있으면 보관함도 안 만든다")

    def test_no_seed_file_at_all_is_the_lacking_case_and_creates_nothing(self):
        world = World(self)
        before = world.listing()
        self.assertEqual(world.provider.preview_make(SAFE, NEVER).lacks, ("no_seed",))
        self.assertEqual(world.listing(), before)

    def test_no_channel_with_generation_on_is_its_own_lack(self):
        world = World(self, seeds=approved_seeds())
        off = [dataclasses.replace(item, generation_enabled=False) for item in ch.default_profiles()]
        world.paths.profiles.write_bytes((json.dumps(ch.profiles_to_dict(off), ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
        preview = world.provider.preview_make(SAFE, NEVER)
        self.assertEqual((preview.can_make, preview.lacks, preview.channels), (False, ("no_channel",), ()))

    def test_full_slots_are_reported_as_full_and_a_preview_with_old_structure_says_so(self):
        world = World(self, seeds=approved_seeds(3))
        world.add(*(candidate(number, 85, "naver_a" if number % 2 else "naver_b", candidate_type="evergreen") for number in range(1, 41)))
        preview = world.provider.preview_make(SAFE, NEVER)
        self.assertEqual(preview.store, "ready")
        self.assertFalse(preview.can_make)
        self.assertIn(preview.lacks[0], ("full", "none"))
        old = World(self, seeds=approved_seeds(3))
        old.add(candidate(1, 85), store_class=v1_class())
        before = old.tree()
        self.assertEqual(old.provider.preview_make(SAFE, NEVER).store, "old_structure")
        self.assertEqual(old.tree(), before, "옛 구조 위의 미리 보기도 아무것도 올리지 않는다")

    def test_the_skip_reasons_are_the_service_fixed_titles_and_never_the_command_line_notes(self):
        world = World(self, seeds=approved_seeds())
        preview = world.provider.preview_make(SAFE, NEVER)
        reasons = {reason for item in preview.channels for reason in item.reasons}
        self.assertTrue(reasons)
        self.assertNotIn("목표에 모자란 경로", reasons, "결과 설명일 뿐 건너뛰는 이유가 아니다")
        for reason in reasons:
            self.assertNotRegex(reason, r"--yes|topics|generate")

    def test_the_preview_never_asks_the_network_or_the_keystore(self):
        world = World(self, seeds=approved_seeds())

        def boom(*args, **kwargs):
            raise AssertionError("미리 보기·후보 만들기는 네트워크·키 보관소를 부르지 않는다")

        world.ctx.get_keystore = boom
        with mock.patch.object(socket.socket, "connect", boom), mock.patch.object(urllib.request, "urlopen", boom):
            world.provider.preview_make(SAFE, NEVER)
            controller = world.controller()
            load(controller)
            drive(controller, controller.start_preview)
            controller.make_dialog()
            self.assertEqual(drive(controller, controller.start_make), ("started", "ok"))


# ---- 4) 후보 만들기(유일한 쓰기) -----------------------------------------------------------------------------------------------------------
class MakeTest(unittest.TestCase):
    def prepared(self, world):
        controller = world.controller()
        load(controller)
        self.assertEqual(drive(controller, controller.start_preview), ("started", "ok"))
        return controller

    @staticmethod
    def dump(path):
        with sqlite3.connect(str(path)) as connection:
            lines = list(connection.iterdump())
        connection.close()
        return lines

    def test_nothing_is_written_before_the_dialog_or_after_a_cancel_and_the_confirmed_make_creates_only_the_store_file(self):
        world = World(self, seeds=approved_seeds())
        before, listing = world.tree(), world.listing()
        controller = self.prepared(world)
        self.assertEqual(world.tree(), before, "미리 보기까지는 0쓰기")
        self.assertEqual(controller.start_make(), ("unconfirmed", None))
        controller.make_dialog()
        self.assertEqual(world.tree(), before, "확인창을 보이는 것만으로는 0쓰기")
        controller.discard_make()
        self.assertEqual(controller.start_make(), ("unconfirmed", None))
        self.assertEqual(world.tree(), before, "취소하면 0쓰기")
        dialog = controller.make_dialog()
        self.assertIn("처음 한 번 새로 만들어요", dialog["body"])
        planned = controller.preview.total_new
        self.assertEqual(drive(controller, controller.start_make), ("started", "ok"))
        created = sorted(set(world.listing()) - set(listing))
        self.assertEqual(created, ["data\\topic_engine\\topic_engine.db"] if os.name == "nt" else ["data/topic_engine/topic_engine.db"], "보관함 파일 하나만 생긴다(설정 파일 셋·사본·잠금은 없다)")
        self.assertEqual(len(world.stored()), planned)
        self.assertEqual(controller.notice, ("ok", f"후보 {planned}개를 만들었어요."))
        self.assertFalse(world.paths.profiles.exists() or world.paths.calendar.exists(), "설정 파일은 만들지 않는다")

    def test_the_new_candidates_are_added_to_the_ones_already_there_and_the_old_ones_are_not_touched(self):
        world = World(self, seeds=approved_seeds())
        world.add(candidate(1, 85), candidate(2, 70, "naver_b"))
        old = {item.candidate_id: item for item in world.stored()}
        controller = self.prepared(world)
        controller.make_dialog()
        self.assertEqual(drive(controller, controller.start_make), ("started", "ok"))
        after = {item.candidate_id: item for item in world.stored()}
        self.assertTrue(set(old) < set(after), "더해진다 — 지워지지 않는다")
        self.assertTrue(all(after[key] == value for key, value in old.items()), "있던 후보는 한 칸도 안 바뀐다")
        self.assertGreater(len(after), 2)
        load(controller)
        self.assertEqual(len(controller.rows()), len(after), "만든 뒤 목록을 다시 읽으면 새 후보가 보인다")

    def test_the_confirmed_make_calls_the_service_once_with_confirmed_true_and_no_trend_provider(self):
        world = World(self, seeds=approved_seeds())
        controller = self.prepared(world)
        controller.make_dialog()
        real = topic_service.generate_candidates
        with mock.patch.object(candidates_adapter.service, "generate_candidates", wraps=real) as spy:
            self.assertEqual(drive(controller, controller.start_make), ("started", "ok"))
        self.assertEqual(spy.call_count, 1)
        kwargs = spy.call_args.kwargs
        self.assertIs(kwargs["confirmed"], True)
        self.assertIsNone(kwargs["trend"])
        self.assertEqual(set(kwargs), {"confirmed", "trend"}, "기준일·목표 개수·채널은 서비스 기본값을 쓴다")

    def test_a_second_click_while_it_is_running_does_not_start_a_second_write(self):
        world = World(self, seeds=approved_seeds())
        controller = self.prepared(world)
        controller.make_dialog()
        real, calls = topic_service.generate_candidates, []

        running, release = threading.Event(), threading.Event()                   # 시간(`sleep`)에 기대지 않고 '첫 쓰기가 도는 중' 을 확실히 만든다 — 시험이 문을 열어 줄 때까지 첫 쓰기가 기다린다

        def slow(ctx, **kwargs):
            calls.append(1)
            running.set()
            if not release.wait(30):
                raise AssertionError("시험이 문을 열어 주지 않았다")
            return real(ctx, **kwargs)

        results = {}
        with mock.patch.object(candidates_adapter.service, "generate_candidates", slow):
            first = controller.start_make(on_done=lambda value, _p: results.setdefault("ok", value), on_error=lambda failure, _p: results.setdefault("failed", failure))
            self.assertTrue(running.wait(30), "첫 쓰기가 서비스까지 들어왔다")
            controller.make_asked = True
            self.assertEqual(controller.start_make(), ("busy", None))
            release.set()
            first[1].join(30)
        self.assertEqual(len(calls), 1)
        controller.apply_write_ok(results["ok"])
        self.assertEqual(len(world.stored()), results["ok"].made)

    def test_the_dialog_says_at_most_the_previewed_count_and_the_result_line_says_the_real_count_when_the_store_changed_in_between(self):
        """독립 검증(P4d 수정 F6) — 서비스는 쓰는 시점에 다시 센다: 미리 본 뒤 다른 곳이 자리를 채우면 실제로 만든 수는 미리 본 수보다 적다. 확인창은 `최대 N개`, 결과 줄은 실제 개수만 말한다(`최대` 가 없다)."""
        world = World(self, seeds=approved_seeds())
        controller = self.prepared(world)
        previewed = controller.preview.total_new
        dialog = controller.make_dialog()
        self.assertGreater(previewed, 2)
        self.assertEqual(dialog["title"], f"후보를 최대 {previewed}개 만들까요?")
        self.assertIn(f"새 후보를 최대 {previewed}개 만들어요", dialog["body"])
        self.assertFalse(world.paths.database.exists())
        world.add(*(candidate(number, 85, "naver_a" if number % 2 else "naver_b", candidate_type="evergreen") for number in range(1, 33)))      # 미리 본 뒤에 다른 곳이 자리를 채웠다
        filled = len(world.stored())
        self.assertEqual(drive(controller, controller.start_make), ("started", "ok"))
        really = len(world.stored()) - filled
        self.assertEqual(filled, 32)
        self.assertTrue(0 < really < previewed, (really, previewed))
        self.assertEqual(controller.notice, ("ok", f"후보 {really}개를 만들었어요."), "결과 줄은 실제로 만든 개수다")
        self.assertNotIn("최대", controller.notice[1])

    def test_the_old_structure_is_upgraded_with_a_copy_and_the_old_candidates_survive(self):
        world = World(self, seeds=approved_seeds())
        world.add(candidate(1, 85), candidate(2, 70, "naver_b"), store_class=v1_class())
        before_dump = self.dump(world.paths.database)
        controller = self.prepared(world)
        self.assertEqual(controller.preview.store, "old_structure")
        dialog = controller.make_dialog()
        self.assertIn("옛 구조라 새 구조로 올려요", dialog["body"])
        self.assertIn("옛 모양 사본을 남겨요", dialog["body"])
        self.assertEqual(drive(controller, controller.start_make), ("started", "ok"))
        copy = world.paths.database.parent / "topic_engine.db.v1.bak"
        self.assertTrue(copy.exists(), "올리기 전에 옛 모양 사본이 남는다")
        self.assertEqual(self.dump(copy), before_dump, "사본은 올리기 전 파일과 내용이 같다")
        with sqlite3.connect(str(world.paths.database)) as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], topic_store.SCHEMA_VERSION)
        connection.close()
        ids = {item.candidate_id for item in world.stored()}
        self.assertTrue({candidate(1, 85).candidate_id, candidate(2, 70, "naver_b").candidate_id} <= ids)

    def test_a_read_only_store_file_fails_with_the_io_sentence_and_leaves_every_byte_and_the_list_as_it_was(self):
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            self.skipTest("관리자(root)는 읽기 전용 파일도 쓸 수 있다")
        world = World(self, seeds=approved_seeds())
        world.add(candidate(1, 85))
        controller = self.prepared(world)
        controller.make_dialog()
        os.chmod(world.paths.database, stat.S_IREAD)
        self.addCleanup(os.chmod, world.paths.database, stat.S_IWRITE | stat.S_IREAD)
        before, listing, ids = world.tree(), world.listing(), [item.candidate.candidate_id for item in controller.rows()]
        status, outcome = drive(controller, controller.start_make)
        self.assertEqual((status, outcome), ("started", "failed"))
        self.assertEqual(controller.notice, ("error", T["cand_fail_io"]))
        self.assertEqual(world.tree(), before, "쓰기 전 상태 그대로(바이트 같음)")
        self.assertEqual(world.listing(), listing, "임시·잠금 파일이 남지 않는다")
        self.assertEqual([item.candidate.candidate_id for item in controller.rows()], ids, "목록이 안 바뀐다")

    def test_a_store_that_another_window_holds_fails_with_the_busy_sentence_and_changes_nothing(self):
        world = World(self, seeds=approved_seeds())
        world.add(candidate(1, 85))
        controller = self.prepared(world)
        controller.make_dialog()
        holder = sqlite3.connect(str(world.paths.database), isolation_level=None, timeout=1)
        holder.execute("BEGIN IMMEDIATE")
        try:
            before, listing = world.tree(), world.listing()
            patched = lambda path: topic_store.open_for_write(path, busy_seconds=0.1)  # noqa: E731
            with mock.patch.object(topic_service, "open_for_write", patched):
                status, outcome = drive(controller, controller.start_make)
            self.assertEqual((status, outcome), ("started", "failed"))
            self.assertEqual(controller.notice, ("error", T["cand_fail_busy"]))
            self.assertEqual(world.tree(), before)
            self.assertEqual(world.listing(), listing)
        finally:
            holder.rollback()
            holder.close()
        self.assertEqual(len(world.stored()), 1, "잠금이 풀린 뒤에도 직전 후보 그대로")

    def test_a_corrupt_store_file_is_never_made_over_and_says_the_corrupt_sentence(self):
        world = World(self, seeds=approved_seeds())
        world.paths.folder.mkdir(parents=True, exist_ok=True)
        world.paths.database.write_bytes(b"not a database " * 200)
        controller = world.controller()
        controller.apply_loaded(cd.CandidatesData((), "ready", (), (), 0, 0, False))
        controller.preview = cd.MakePreview("ready", (cd.ChannelPreview("naver_a", "가", 3, 20, 20),), 3, 1, 0, (), False)
        controller.make_dialog()
        before = world.tree()
        self.assertEqual(drive(controller, controller.start_make), ("started", "failed"))
        self.assertEqual(controller.notice, ("error", T["cand_fail_corrupt"]))
        self.assertEqual(world.tree(), before)

    def test_a_broken_profile_file_stops_the_make_before_anything_is_written(self):
        world = World(self, seeds=approved_seeds())
        controller = self.prepared(world)
        controller.make_dialog()
        world.paths.profiles.write_bytes(b"{broken")                              # 미리 본 뒤에 다른 곳에서 설정 파일이 깨졌다
        before = world.tree()
        self.assertEqual(drive(controller, controller.start_make), ("started", "failed"))
        self.assertEqual(controller.notice, ("error", T["cand_fail_invalid"]))
        self.assertEqual(world.tree(), before)
        self.assertFalse(world.paths.database.exists(), "보관함도 안 만들어졌다")

    def test_the_adapter_refuses_a_make_without_anything_to_make(self):
        world = World(self)
        with self.assertRaises(cd.CandidateFailure):
            world.provider.make_candidates(cd.MakePreview("missing", (), 0, 0, 0, ("no_seed",), False), SAFE, NEVER)
        self.assertFalse(world.paths.folder.exists())


# ---- 4b) 어댑터 → 알림 연결(독립 검증 F2-3 — 변이 A03·A05·A06·A07: 코드는 맞고 시험이 못 잡던 곳) -----------------------------------------------------------
class AdapterToNoticeTest(unittest.TestCase):
    """실제 보관함·진짜 서비스·진짜 어댑터로, 서비스가 센 값(자리·같은 후보·저장하지 않은 후보·후보 생성 켜짐)이 화면의 확인창·준비 안내·결과 문장까지 **같은 수로** 가는지 견준다.
    기댓값은 어댑터가 아니라 서비스의 계획(`plan_candidates`)·설정 파일에서 따로 읽는다."""

    @staticmethod
    def planned(world):
        return topic_service.plan_candidates(world.ctx, trend=None)

    def previewed(self, world):
        controller = world.controller()
        load(controller)
        self.assertEqual(drive(controller, controller.start_preview), ("started", "ok"))
        return controller

    def test_the_skipped_same_candidates_are_counted_in_the_dialog_and_in_the_result_sentence(self):
        world = World(self, seeds=approved_seeds(3))
        chosen = next(item for item in self.planned(world).plans if item.enabled and item.candidates).candidates[0]
        world.add(dataclasses.replace(chosen, candidate_id=f"tc-{chosen.channel}-seed-{'ab' * 8}"))        # 채널·Seed·의도·관점이 같은 후보를 다른 번호로 미리 넣어 둔다 — 서비스가 '같은 후보' 로 건너뛴다
        expected = self.planned(world)
        skipped, new = sum(item.duplicates for item in expected.plans), expected.total
        self.assertGreater(skipped, 0, "시험 준비: 서비스가 같은 후보를 건너뛴다")
        controller = self.previewed(world)
        self.assertEqual((controller.preview.duplicates, controller.preview.total_new), (skipped, new))
        self.assertIn(T["cand_make_skip_dup"].format(n=skipped), controller.make_dialog()["body"])
        self.assertEqual(drive(controller, controller.start_make), ("started", "ok"))
        self.assertEqual(controller.notice, ("ok", f"후보 {new}개를 만들었어요. 같은 후보 {skipped}개는 건너뛰었어요."))
        self.assertEqual(len(world.stored()), 1 + new)

    def test_the_candidates_left_unsaved_for_a_key_shape_are_counted_in_the_result_sentence_and_never_reach_the_store(self):
        """키 모양 씨앗은 보통 후보를 만들기 **전에** 빠져서 저장 직전의 거름(방어선)에는 걸릴 것이 없다 — 방어선 쪽을 진짜 보관함·서비스·어댑터로 지나게 하려고 앞의 거름만 끈다(키 모양 검사 자체는 진짜)."""
        seeds = approved_seeds(3)
        seeds[0] = dataclasses.replace(seeds[0], keyword=f"예시 {KEY_SHAPED}")
        world = World(self, seeds=seeds)
        with mock.patch.object(topic_service, "_split_key_shaped_seeds", lambda found: (tuple(found), ())):
            expected = self.planned(world)
            held, new = sum(len(item.withheld) for item in expected.plans), expected.total
            self.assertGreater(held, 0, "시험 준비: 저장 직전 거름이 키 모양 후보를 뺀다")
            controller = self.previewed(world)
            self.assertEqual(controller.preview.total_new, new, "미리 보기는 저장하지 않을 후보를 세지 않는다")
            controller.make_dialog()
            self.assertEqual(drive(controller, controller.start_make), ("started", "ok"))
        self.assertEqual(controller.notice, ("ok", f"후보 {new}개를 만들었어요. 키·토큰처럼 보이는 글이 든 후보 {held}개는 저장하지 않았어요."))
        self.assertEqual(len(world.stored()), new)
        self.assertNotIn(KEY_SHAPED, json.dumps([item.to_dict() for item in world.stored()], ensure_ascii=False))

    def test_the_prep_card_says_full_when_the_slots_are_full_and_none_when_nothing_new_is_left(self):
        full = World(self, seeds=approved_seeds(3))
        full.add(*(candidate(number, 85, "naver_a" if number % 2 else "naver_b", candidate_type="evergreen") for number in range(1, 41)))
        preview = full.provider.preview_make(SAFE, NEVER)
        self.assertEqual((preview.can_make, preview.lacks), (False, ("full",)), "목표 개수가 찼으면 `full`")
        controller = self.previewed(full)
        self.assertIsNone(controller.make_dialog())
        self.assertIn(T["cand_prep_full"], controller.view()["prep"]["lines"])
        self.assertNotIn(T["cand_prep_none"], controller.view()["prep"]["lines"])
        left = World(self, seeds=approved_seeds(3))                                                      # 씨앗 셋 — 두 번 만들면 더 만들 후보가 없지만 자리는 남는다
        for _ in range(2):
            self.assertTrue(left.provider.preview_make(SAFE, NEVER).can_make)
            controller = self.previewed(left)
            controller.make_dialog()
            self.assertEqual(drive(controller, controller.start_make), ("started", "ok"))
        preview = left.provider.preview_make(SAFE, NEVER)
        self.assertTrue(all(item.remaining and item.remaining > 0 for item in preview.channels), "자리는 남아 있다")
        self.assertEqual((preview.can_make, preview.lacks), (False, ("none",)), "자리가 남았는데 새로 만들 것이 없으면 `none`")
        controller = self.previewed(left)
        self.assertIsNone(controller.make_dialog())
        self.assertIn(T["cand_prep_none"], controller.view()["prep"]["lines"])
        self.assertNotIn(T["cand_prep_full"], controller.view()["prep"]["lines"])

    def test_a_channel_turned_off_in_the_profile_file_is_reported_off_and_is_neither_a_chip_nor_in_the_preview(self):
        world = World(self, seeds=approved_seeds())
        off = [dataclasses.replace(item, generation_enabled=False) if item.key == "naver_b" else item for item in ch.default_profiles()]
        world.paths.folder.mkdir(parents=True, exist_ok=True)
        world.paths.profiles.write_bytes((json.dumps(ch.profiles_to_dict(off), ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
        world.add(candidate(1, 85, "naver_a"))                                                           # 거르기 칩은 후보가 하나라도 있어야 보인다
        controller = world.controller()
        data = load(controller)
        info = data.channel_map()
        self.assertEqual({key: item.enabled for key, item in info.items() if key in ("naver_a", "naver_b")}, {"naver_a": True, "naver_b": False}, "프로필 파일의 후보 생성 켜짐이 그대로 간다")
        chips = [chip["key"] for chip in controller.view()["filters"]["channel"]]
        self.assertIn("naver_a", chips)
        self.assertNotIn("naver_b", chips, "후보도 없고 후보 생성도 꺼진 채널은 거르기 칩에 없다")
        preview = world.provider.preview_make(SAFE, NEVER)
        self.assertEqual([item.key for item in preview.channels], ["naver_a"])


# ---- 4c) 운영자 P4d 완료 조건 ⑧(저장 실패가 기존 기능을 막지 않음)과 `PIPELINE_PAUSE` 규칙(2026-11-09 지시) ---------------------------------------------------
class KeepsWorkingTest(unittest.TestCase):
    """저장(후보 만들기)이 실패해도 흐름이 갇히지 않고 나머지 기능이 그대로이며, 데스크톱은 GitHub 저장소 변수 `PIPELINE_PAUSE` 를 읽지도 등록·수정·삭제하지도 않아 그 값이 `true` 여도 로컬 기능이 똑같이 돈다."""
    PAUSE = "PIPELINE_" + "PAUSE"                                                                      # 이 파일 자신이 아래 소스 훑기에 걸리지 않게 이어 붙인다

    def test_a_failed_make_resets_the_flow_leaves_nothing_behind_and_the_same_flow_works_again_once_the_cause_is_gone(self):
        world = World(self, seeds=approved_seeds())
        world.add(candidate(1, 85))
        controller = world.controller()
        load(controller)
        self.assertEqual(drive(controller, controller.start_preview), ("started", "ok"))
        controller.make_dialog()
        holder = sqlite3.connect(str(world.paths.database), isolation_level=None, timeout=1)             # 다른 창이 보관함을 쓰는 중
        holder.execute("BEGIN IMMEDIATE")
        before, listing = world.tree(), world.listing()
        try:
            with mock.patch.object(topic_service, "open_for_write", lambda path: topic_store.open_for_write(path, busy_seconds=0.1)):
                self.assertEqual(drive(controller, controller.start_make), ("started", "failed"))
        finally:
            holder.rollback()
            holder.close()
        self.assertEqual(controller.notice, ("error", T["cand_fail_busy"]))
        self.assertEqual((controller.preview, controller.make_asked, controller.busy), (None, False, False), "실패하면 미리 본 것과 '확인창을 보였다' 표시가 모두 처음으로 돌아온다")
        self.assertEqual(controller.start_make(), ("unavailable", None), "미리 보기와 확인창 없이 다시 쓰는 길은 없다")
        self.assertEqual((world.tree(), world.listing()), (before, listing), "실패는 바이트도 임시·잠금 파일도 남기지 않는다")
        self.assertTrue(controller.view()["make"]["enabled"], "`후보 만들기` 는 다시 켜져 있다")
        self.assertEqual(len(controller.rows()), 1, "기존 후보와 목록은 그대로다")
        self.assertEqual(drive(controller, controller.start_preview), ("started", "ok"), "원인(다른 창)이 사라지면 같은 화면에서 다시 미리 본다")
        planned = controller.preview.total_new
        self.assertGreater(planned, 0)
        self.assertIsNotNone(controller.make_dialog())
        self.assertEqual(drive(controller, controller.start_make), ("started", "ok"))
        self.assertEqual(controller.notice, ("ok", f"후보 {planned}개를 만들었어요."))
        self.assertEqual(len(world.stored()), 1 + planned, "다시 시도한 만들기가 정상으로 저장됐다")

    def test_no_code_of_the_desktop_reads_writes_or_deletes_the_pipeline_pause_repository_variable(self):
        root = Path(__file__).resolve().parent.parent
        banned = (self.PAUSE, "gh variable", "actions/variables")
        scanned, hits = 0, []
        for folder in (root / "src", root / "scripts"):
            for path in sorted(folder.rglob("*.py")):
                body = path.read_text(encoding="utf-8")
                scanned += 1
                hits += [f"{path.relative_to(root).as_posix()}: {word}" for word in banned if word in body]
        self.assertGreater(scanned, 120, "소스를 실제로 훑는다")
        self.assertEqual(hits, [], "데스크톱 코드는 저장소 변수 `PIPELINE_PAUSE` 를 읽지도(환경·API) 등록·수정·삭제하지도 않는다")
        self.assertEqual([word for word in banned if word in "see gh variable set X and actions/variables " + self.PAUSE], list(banned), "대조: 식이 금지 글을 실제로 알아본다")

    def test_the_local_candidate_flow_gives_the_same_results_when_the_pause_variable_is_true(self):
        def boom(*args, **kwargs):
            raise AssertionError("화면·후보 만들기는 키 보관소를 부르지 않는다")

        results = []
        for env in ({}, {self.PAUSE: "true"}):
            with mock.patch.dict(os.environ, env):
                world = World(self, seeds=approved_seeds(3))
                world.ctx = dataclasses.replace(world.ctx, env=None)                                       # 진짜 환경 변수를 읽는 맥락(시험 맥락은 보통 환경을 비워 둔다)
                world.ctx.get_keystore = boom
                self.assertEqual(os.environ.get(self.PAUSE), env.get(self.PAUSE))
                controller = world.controller()
                load(controller)
                self.assertEqual(drive(controller, controller.start_preview), ("started", "ok"))
                planned = controller.preview.total_new
                controller.make_dialog()
                self.assertEqual(drive(controller, controller.start_make), ("started", "ok"))
                results.append((planned, controller.notice, len(world.stored()), controller.make_info()))
        self.assertEqual(results[0], results[1], "변수가 true 여도 읽기·미리 보기·만들기가 똑같이 돈다")
        self.assertGreater(results[1][0], 0)
        self.assertEqual(results[1][1][0], "ok")


# ---- 5) 소스 규칙 ----------------------------------------------------------------------------------------------------------------------
class SourceRulesTest(unittest.TestCase):
    def test_the_adapter_reaches_the_service_only_through_three_topic_functions_and_three_setting_reads(self):
        tree = ast.parse((UI_DIR / "candidates_adapter.py").read_text(encoding="utf-8"))
        used = sorted({ast.unparse(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call) and ast.unparse(node.func).startswith(("service.", "topic_files."))})
        self.assertEqual(used, ["service.generate_candidates", "service.list_candidates", "service.plan_candidates", "topic_files.load_profiles", "topic_files.load_seeds", "topic_files.topic_paths"])
        text_of = (UI_DIR / "candidates_adapter.py").read_text(encoding="utf-8")
        writes = [ast.unparse(node) for node in ast.walk(tree) if isinstance(node, ast.Call) and ast.unparse(node.func) == "service.generate_candidates"]
        self.assertEqual(writes, ["service.generate_candidates(ctx, confirmed=True, trend=None)"], "쓰는 서비스 호출은 한 곳이고 확인 표시와 관심도 없음이 늘 같이 간다")
        self.assertNotIn("security.keystore", text_of)
        for banned in ("os.", "open(", "write_json", "save_seeds", "init_topics", "cleanup_hold", "open_for_write", "sqlite3", "shutil"):
            self.assertNotIn(banned, text_of)

    def test_the_only_function_that_writes_is_make_candidates(self):
        tree = ast.parse((UI_DIR / "candidates_adapter.py").read_text(encoding="utf-8"))
        writers = [node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and "generate_candidates" in ast.unparse(node)]
        self.assertEqual(writers, ["make_candidates"])
        self.assertIn("confirmed", ast.unparse(next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "make_candidates")))

    def test_the_service_test_allow_list_for_low_level_writes_was_not_widened(self):
        source = (Path(__file__).resolve().parent / "test_service_safety.py").read_text(encoding="utf-8")
        self.assertNotIn("candidates_adapter", source)
        self.assertNotIn("candidate_rules", source)

    def test_the_home_provider_pairs_with_the_service_and_the_fake_provider_pairs_with_the_fake(self):
        self.assertIsInstance(adapters.ServiceHomeProvider("x").candidates_provider(), candidates_adapter.ServiceCandidatesProvider)
        self.assertIsInstance(services.FakeHomeProvider().candidates_provider(), cd.FakeCandidatesProvider)

    def test_the_home_provider_hands_its_data_folder_and_context_factory_to_the_candidate_pair_and_the_app_state_uses_that_pair(self):
        """독립 검증(P4d 수정 F2-1) — `candidates=` 를 직접 넘기는 시험은 이 배선을 건너뛴다. 홈 공급자(`--data-dir`)와 짝인 후보 공급자가 같은 폴더·같은 맥락 공장을 쓰고 `AppState` 가 그 짝을 쓴다(예시 공급자로 새지 않는다)."""
        with tempfile.TemporaryDirectory() as folder:
            def factory(data_dir=None):
                raise AssertionError("배선만 본다 — 맥락을 만들지 않는다")

            home = adapters.ServiceHomeProvider(folder, context_factory=factory)
            pair = home.candidates_provider()
            self.assertIsInstance(pair, candidates_adapter.ServiceCandidatesProvider)
            self.assertEqual(pair._data_dir, folder, "짝 공급자는 홈과 같은 데이터 폴더를 쓴다")
            self.assertIs(pair._factory, factory)
            state = app_state.AppState(home)
            self.assertIsInstance(state.candidates_provider, candidates_adapter.ServiceCandidatesProvider, "실제 홈 공급자를 고르면 후보 화면도 실제 쪽이다 — 예시 공급자로 새지 않는다")
            self.assertEqual(state.candidates_provider._data_dir, folder)
            self.assertIs(state.candidates_provider._factory, factory)
            self.assertIs(state.candidates.provider, state.candidates_provider, "컨트롤러가 쓰는 공급자도 같은 것이다")
            self.assertFalse(state.candidates_provider.sample)
            explicit = cd.FakeCandidatesProvider()
            self.assertIs(app_state.AppState(home, candidates=explicit).candidates_provider, explicit, "직접 넘기면 그것이 이긴다(시험·화면 진입점)")
        fake = app_state.AppState(services.FakeHomeProvider())
        self.assertIsInstance(fake.candidates_provider, cd.FakeCandidatesProvider, "예시 홈 공급자의 짝은 예시 후보 공급자")
        self.assertTrue(fake.candidates_provider.sample)
        self.assertIsNone(adapters.ServiceHomeProvider().candidates_provider()._data_dir, "데이터 폴더를 안 정하면 짝도 안 정한다(기본 위치)")

    def test_the_failure_kinds_the_adapter_knows_are_the_ones_the_screen_has_sentences_for(self):
        self.assertTrue(set(candidates_adapter.KIND_OF_CODE.values()) <= set(cd.KINDS_OF_FAILURE))
        for kind in cd.KINDS_OF_FAILURE:
            self.assertIn("cand_fail_" + kind, T)
        for code, kind in candidates_adapter.KIND_OF_CODE.items():
            made = candidates_adapter.failure_of(AppError(code, {"파일": "x"}))
            self.assertEqual((made.kind, made.user_message), (kind, T["cand_fail_" + kind]), code)
            self.assertNotIn("x", made.user_message)


if __name__ == "__main__":
    unittest.main()
