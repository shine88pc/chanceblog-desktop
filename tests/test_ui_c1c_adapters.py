"""홈 데이터(UI-C1c)의 어댑터 시험 — 실제 서비스 층(주제 엔진의 우수 후보 읽기·글 목록)을 **읽기만** 해서 홈의 새 구역 값(`BoardData`)으로 바꾼다. PySide6 없이 돈다(네트워크·시크릿·실제 시계 없음).

지키는 것: 채널 A·B 추천은 서비스가 고른 앞줄을 최대 5개 · 후보 천 개에서도 서비스를 한 번만 읽고 5개만 받는다 · 월 검색량·문서 수·이전 점수는 가져오지 않는다 · 보관함이 없으면 만들지 않고(정상 빈 상태) 못 열면 그 구역만 오류 ·
표시 이름은 런타임에 읽는다(사용자가 정한 이름 → 채널 프로필 → 서비스 이름, 가려서 줄임) · 작성 중 초안은 승인 전 글 최대 5개 · 구역마다 따로 실패하고 취소는 구역 사이마다 본다 · 쓰는 길이 하나도 불리지 않는다.
"""
import ast
import contextlib
import dataclasses
import json
import re
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import service_support as support  # noqa: E402
import topics_support as ts  # noqa: E402
from chanceblog_desktop.content import status as st  # noqa: E402
from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.service import projects  # noqa: E402
from chanceblog_desktop.service import topic_files as tf  # noqa: E402
from chanceblog_desktop.service import topics as tp  # noqa: E402
from chanceblog_desktop.topicdb.store import open_for_write  # noqa: E402
from chanceblog_desktop.topics import channels as channel_module  # noqa: E402
from chanceblog_desktop.ui import adapters  # noqa: E402
from chanceblog_desktop.ui.core import app_state, board_view, jobs, services, text  # noqa: E402

KEY = "AI" + "za" + "R" * 35                       # 구글 키 모양의 가짜 값(조각을 이어 만들어 저장소에는 키 문자열이 없다)
SHORT_KEY = "AK" + "IA" + "ABCDEFGHJKLMNPQR"        # 20자라 채널 프로필 파일(표시 이름 30자까지)에도 쓸 수 있는 키 모양(AWS)
SECRET_PATH = "C:" + chr(92) + "비밀폴더" + chr(92) + "값"
TREND = {"trend_ratio": 73, "trend_period": "2025-11-04~2026-11-04", "trend_compared_group": ("예시 하나", "예시 둘"), "trend_queried_on": "2026-11-04", "data_status": "sufficient"}
STAMP = "2026-11-10T01:00:00Z"
NO_STATE = lambda: False                           # noqa: E731


def leaks(shown, key=KEY, size=6):
    return sorted({key[i:i + size] for i in range(len(key) - size + 1) if key[i:i + size] in shown})


def texts_of(value):
    """뷰모델 속 모든 글(딕셔너리 키는 빼고 값만). `id` 칸은 글이 아니다(UI-C1d, D-201 — 추천 줄을 눌렀을 때 서랍에 넘기는 열쇠)."""
    if isinstance(value, dict):
        return " ".join(texts_of(item) for key, item in value.items() if key != "id")
    if isinstance(value, (list, tuple)):
        return " ".join(texts_of(item) for item in value)
    return "" if value is None else str(value)


def cand(index, final=80, channel="naver_a", **more):
    """검증을 모두 통과하는 엔진 후보 — 번호·시각이 늘 같다."""
    values = {"candidate_id": f"tc-{channel}-seed-{index:016x}", "cluster": f"cluster-{index % 40}", "topic": f"예시 주제 {index}번 글", "created_at": f"2026-11-04T09:{(index // 60) % 60:02d}:{index % 60:02d}Z"}
    values.update(more)
    return ts.rated(final, channel=channel, **values)


class World:
    """임시 폴더의 사용자 데이터 폴더와 Context — 주제 엔진 보관함·글 보관함을 시험이 직접 채운다."""

    def __init__(self, tmp):
        self.ctx = support.make_ctx(tmp)
        self.paths = tf.topic_paths(self.ctx.workspace)

    def add(self, *items):
        with open_for_write(self.paths.database) as store:
            store.add_candidates(lambda existing: list(items), now=STAMP)

    def put_profiles(self, changes):
        """채널 프로필 파일을 쓴다 — `changes` 는 {채널 이름: {칸: 값}}(고치지 않은 채널은 기본 프로필 그대로)."""
        profiles = [dataclasses.replace(profile, **changes.get(profile.key, {})) for profile in channel_module.default_profiles()]
        self.paths.folder.mkdir(parents=True, exist_ok=True)
        self.paths.profiles.write_text(json.dumps(channel_module.profiles_to_dict(profiles), ensure_ascii=False), encoding="utf-8")

    def provider(self, **kwargs):
        return adapters.ServiceHomeProvider(context_factory=lambda data_dir=None: self.ctx, **kwargs)

    def load(self, cancelled=NO_STATE, **kwargs):
        return self.provider(**kwargs).load_home(lambda *a: None, cancelled)

    def draft(self, title, naver_a=None, naver_b=None, updated="2026-11-05T00:00:00Z"):
        """승인 전 글 — `naver_a`·`naver_b` 에 'generated'(초안 생성됨)·'review'(검토 필요)를 준다. 마지막으로 고친 때는 `updated`."""
        steps = {"generated": (st.DRAFT_GENERATED,), "review": (st.DRAFT_GENERATED, st.REVIEW_REQUIRED)}
        view = projects.new_project(self.ctx, title, support.ko_text())
        with self.ctx.store() as store:
            project = store.load(view.project_id)
            for platform, stage in (("naver_a", naver_a), ("naver_b", naver_b)):
                for status in steps.get(stage, ()):
                    project.transition(platform, status, now=updated)
            store.save(project)
        return view.project_id


def published(world, title, stamps, updated="2026-11-05T00:00:00Z"):
    """발행한 글 — `stamps` 는 {플랫폼: 발행한 때}. 마지막으로 고친 때(`updated_at`)는 `updated` 로 따로 정한다(발행한 때와 달라도 된다)."""
    view = projects.new_project(world.ctx, title, support.ko_text())
    with world.ctx.store() as store:
        project = store.load(view.project_id)
        for platform, stamp in stamps.items():
            variant = project.variant(platform)
            variant.status = st.PUBLISHED if platform == "github_pages" else st.PUBLISHED_MANUAL
            variant.published_url = "https://blog.naver.com/example/1" if platform.startswith("naver") else "https://example.invalid/post"
            variant.published_at = stamp
        project.updated_at = updated
        store.save(project)
    return view.project_id


def row_for(project_id, title, updated, statuses, error=""):
    return projects.ProjectRow(project_id, title, 1, updated, statuses, error)


class FakeEngine:
    """주제 엔진을 읽는 곳(`top`·`names`)의 가짜 — 부른 이름을 적어 두고, 시험이 정한 결과나 오류를 낸다."""

    def __init__(self, channels=None, store_state="ready", names=None, error=None, names_error=None):
        self.channels, self.store_state, self._names, self.error, self.names_error, self.calls = channels, store_state, names or {}, error, names_error, []

    def top(self, ctx):
        self.calls.append("top")
        if self.error is not None:
            raise self.error
        return SimpleNamespace(store_state=self.store_state, channels=self.channels if self.channels is not None else (top_channel("naver_a"), top_channel("naver_b")))

    def names(self, ctx):
        self.calls.append("names")
        if self.names_error is not None:
            raise self.names_error
        return dict(self._names)


def top_channel(code, rows=(), enabled=True, name=None, problems=()):
    return SimpleNamespace(channel=code, enabled=enabled, name=name or ("기본 " + code), rows=tuple(rows), shortfall=0, problems=tuple(problems))


class EngineRowsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.world = World(self.tmp.name)

    def channels(self, data=None):
        return {item.key: item for item in (data or self.world.load()).board.channels}

    def test_a_store_with_candidates_gives_rows_best_first_with_whole_scores_and_interest_labels_only(self):
        self.world.add(cand(1, 92, trend_status="rising", **TREND), cand(2, 84, cluster="other-a", trend_status="flat", **TREND), cand(3, 70, cluster="other-b", trend_status="falling", **TREND),
                       cand(4, 66, cluster="other-c"), cand(5, 90, channel="naver_b", search_demand_count=4200, search_count_source="예시 출처"))
        data = self.world.load()
        shown = self.channels(data)
        self.assertEqual([(row.title, row.score, row.interest, row.prev_score, row.sample) for row in shown["A"].rows],
                         [("예시 주제 1번 글", 92, "rising", None, False), ("예시 주제 2번 글", 84, "flat", None, False), ("예시 주제 3번 글", 70, "falling", None, False), ("예시 주제 4번 글", 66, None, None, False)])
        self.assertEqual([(row.title, row.score, row.interest) for row in shown["B"].rows], [("예시 주제 5번 글", 90, None)])
        self.assertEqual((shown["A"].state, shown["A"].reason, shown["A"].enabled, shown["B"].enabled, shown["A"].skipped), ("ok", "", True, True, 0))
        self.assertFalse(data.board.sample)
        for item in shown.values():                                                                          # 모든 점수는 정수이고 줄에는 검색량·문서 수 칸이 없다
            for row in item.rows:
                self.assertIsInstance(row.score, int)
                self.assertEqual({field.name for field in dataclasses.fields(row)}, {"id", "title", "score", "prev_score", "interest", "sample"})
        view = app_state.AppState(self.world.provider())
        view.apply_home(data)
        flat = texts_of(view.home_view()["board"])
        for piece in ("4200", "4,200", "예시 출처", "검색량"):
            self.assertNotIn(piece, flat, piece)                                                           # 서비스가 가진 실제 검색 횟수도 가져오지 않는다

    def test_the_rows_are_exactly_what_the_service_picked_in_its_order_and_never_more_than_five(self):
        for number in range(1, 41):                                                                         # 채널당 20개 묶음 × 2개 = 서비스가 12개까지 고르도록 프로필의 top_n 을 12 로 올린다
            self.world.add(cand(number, 99 - number // 2, cluster=f"c-{(number + 1) // 2}"), cand(100 + number, 98 - number // 2, channel="naver_b", cluster=f"d-{(number + 1) // 2}"))
        self.world.put_profiles({"naver_a": {"top_n": 12}, "naver_b": {"top_n": 12}})
        service = {item.channel: item for item in tp.top_candidates(self.world.ctx).channels}
        self.assertEqual((len(service["naver_a"].rows), len(service["naver_b"].rows)), (12, 12), "서비스는 프로필이 정한 수만큼 준다")
        shown = self.channels()
        for key, code in (("A", "naver_a"), ("B", "naver_b")):
            self.assertEqual([row.id for row in shown[key].rows], [row.candidate.candidate_id for row in service[code].rows][:5], key)      # 서비스의 순서 그대로 앞의 다섯

    def test_a_thousand_candidates_are_read_with_one_service_call_and_only_five_rows_per_channel_come_back(self):
        items = [cand(number, 65 + (number * 7) % 35, "naver_a" if number % 2 else "naver_b") for number in range(1, 1001)]
        self.world.add(*items)

        class Counting(adapters.ServiceEngine):
            def __init__(self):
                self.tops = 0

            def top(self, ctx):
                self.tops += 1
                return super().top(ctx)

        engine = Counting()
        reads = ("top_candidates", "list_candidates", "status", "read_blog_history", "show_candidate", "review_holds", "plan_candidates", "check_files")      # 주제 엔진 서비스의 읽는 함수들
        started = time.monotonic()
        with contextlib.ExitStack() as stack:
            spies = {name: stack.enter_context(mock.patch.object(tp, name, wraps=getattr(tp, name))) for name in reads if hasattr(tp, name)}
            data = self.world.load(engine=engine)
        elapsed = time.monotonic() - started
        self.assertEqual(engine.tops, 1, "서비스 읽기는 한 번뿐이다(후보 전체를 두 번 읽지 않는다)")
        self.assertEqual({name: spy.call_count for name, spy in spies.items() if spy.call_count}, {"top_candidates": 1}, "주제 엔진 서비스의 읽는 함수는 `top_candidates` 하나를 한 번만 부른다 — 후보 전체를 읽는 다른 함수는 부르지 않는다")
        shown = self.channels(data)
        self.assertEqual((len(shown["A"].rows), len(shown["B"].rows)), (5, 5))
        service = {item.channel: item for item in tp.top_candidates(self.world.ctx).channels}
        self.assertEqual([row.id for row in shown["A"].rows], [row.candidate.candidate_id for row in service["naver_a"].rows])
        self.assertLess(elapsed, 60, "후보 천 개를 읽는 데 걸린 시간(초) — 서비스가 후보 전체를 읽는 비용이라 느릴 수 있어도 끝나야 한다")

    def test_a_store_that_is_not_there_is_a_normal_empty_state_and_nothing_is_created(self):
        before = support.tree_snapshot(self.world.ctx.workspace.root)
        shown = self.channels()
        self.assertEqual([(item.state, item.reason, item.rows) for item in shown.values()], [("unavailable", "missing", ())] * 2)
        self.assertFalse(self.world.paths.folder.exists(), "읽기만 하는 화면은 보관함 폴더를 만들지 않는다")
        self.assertEqual(support.tree_snapshot(self.world.ctx.workspace.root), before)
        self.world.paths.folder.mkdir(parents=True)
        self.world.paths.database.write_bytes(b"")                                                          # 0바이트 파일(만들다 멈춘 흔적)도 '아직 없음'
        self.assertEqual([(item.state, item.reason) for item in self.channels().values()], [("unavailable", "missing")] * 2)
        self.assertEqual(self.world.paths.database.read_bytes(), b"")

    def test_an_old_structure_store_is_reported_as_old_and_not_read_or_changed(self):
        engine = FakeEngine(store_state="old_structure")
        shown = self.channels(self.world.load(engine=engine))
        self.assertEqual([(item.state, item.reason, item.rows) for item in shown.values()], [("unavailable", "old", ())] * 2)
        self.assertEqual({item.enabled for item in shown.values()}, {True})                                  # 채널 정보(켜짐)는 그대로 알려 준다

    def test_a_store_that_cannot_be_opened_fails_only_that_section_with_an_easy_sentence_and_the_code(self):
        self.world.paths.folder.mkdir(parents=True)
        self.world.paths.database.write_bytes(b"this is not a database " * 200)
        project_id = self.world.draft("초안 하나", naver_a="review")
        before = self.world.paths.database.read_bytes()
        data = self.world.load()
        for item in data.board.channels:
            self.assertEqual((item.state, item.rows, item.failure.code, item.failure.user_message), ("failed", (), "TOPIC_STORE_CORRUPT", "후보 보관함을 읽지 못했어요. 파일은 고치거나 지우지 않았어요. 계속되면 진단 정보를 함께 알려 주세요."))
            self.assertNotIn("topics restore", item.failure.user_message)                                    # 명령줄 글이 화면 문장에 없다
        self.assertEqual(self.world.paths.database.read_bytes(), before, "깨진 파일은 고치거나 지우지 않는다")
        self.assertEqual([(row.id, row.stage) for row in data.board.drafts.rows], [(project_id, "review")])      # 다른 구역은 그대로 읽힌다
        self.assertEqual(len(data.topics), 0)                                                                # 옛 홈 데이터도 그대로 읽힌다

    def test_each_engine_read_error_has_its_own_easy_sentence_without_commands_and_unknown_codes_use_the_catalog(self):
        expected = {"TOPIC_STORE_CORRUPT": "board_err_store", "CANDIDATE_INVALID": "board_err_store", "TOPIC_STORE_VERSION_UNSUPPORTED": "board_err_newer", "TOPIC_STORE_LOCKED": "board_err_locked",
                    "TOPIC_STORE_RECOVERY_PENDING": "board_err_pending", "TOPIC_FILE_INVALID": "board_err_profiles", "CONTENT_INVALID": "board_err_profiles"}
        self.assertEqual(adapters.ENGINE_WORDED, expected)
        for code, key in expected.items():
            failure = adapters.engine_failure(AppError(code, {"파일": "topic_engine.db", "항목": "채널", "이유": "예시"}))
            self.assertEqual((failure.code, failure.user_message), (code, text.T[key]), code)
            self.assertNotRegex(failure.user_message, r"`|--|topics |\.bak|\.db|json", code)
        self.assertEqual(text.T["board_err_newer"], "더 새로운 버전의 프로그램이 만든 후보 보관함이라 열지 않았어요. 프로그램을 최신 버전으로 업데이트해 주세요.")
        self.assertEqual(text.T["board_err_locked"], "후보 보관함을 다른 곳에서 쓰고 있어 잠시 열지 못했어요. 끝난 뒤 다시 읽어 주세요.")
        other = adapters.engine_failure(AppError("DATA_DIR_UNSAFE", {"경로": "가" * 100 + " " + KEY}))
        self.assertIn("데이터를 둘 폴더가 안전하지 않습니다", other.user_message)
        self.assertEqual(leaks(other.user_message, KEY, 5), [])                                              # 카탈로그 문장은 폴더 경로를 싣지만 그 속의 키 모양은 가려진다

    def test_real_engine_errors_for_a_newer_store_and_a_bad_profile_file_are_told_with_their_own_sentences(self):
        import sqlite3
        self.world.add(cand(1, 80))
        connection = sqlite3.connect(str(self.world.paths.database))
        connection.execute("PRAGMA user_version = 9")
        connection.commit()
        connection.close()
        self.assertEqual({item.failure.code for item in self.channels().values()}, {"TOPIC_STORE_VERSION_UNSUPPORTED"})
        self.assertIn("최신 버전으로 업데이트", next(iter(self.channels().values())).failure.user_message)
        connection = sqlite3.connect(str(self.world.paths.database))
        connection.execute("PRAGMA user_version = 1")
        connection.commit()
        connection.close()
        self.world.paths.profiles.write_text("{broken", encoding="utf-8")
        shown = self.channels()
        self.assertEqual({item.failure.code for item in shown.values()}, {"TOPIC_FILE_INVALID"})
        self.assertEqual(self.world.paths.profiles.read_text(encoding="utf-8"), "{broken", "깨진 설정 파일은 고치지 않는다")

    def test_an_unexpected_exception_in_the_engine_fails_only_that_section_and_shows_no_content_of_it(self):
        boom = FakeEngine(error=RuntimeError("내부 " + SECRET_PATH + " " + KEY))
        data = self.world.load(engine=boom)
        for item in data.board.channels:
            self.assertEqual((item.state, item.failure.code, item.failure.user_message), ("failed", "RuntimeError", text.T["data_unreadable"]))
            self.assertEqual(leaks(repr(item) + item.failure.user_message, KEY, 5), [])
            self.assertNotIn("비밀폴더", repr(item))
        self.assertEqual(data.board.drafts.state, "ok")                                                      # 다른 구역은 그대로

    def test_a_cancel_raised_inside_the_engine_read_is_not_swallowed(self):
        with self.assertRaises(jobs.JobCancelled):
            self.world.load(engine=FakeEngine(error=jobs.JobCancelled()))

    def test_the_names_come_from_the_naver_profile_first_then_the_channel_profile_then_the_service_name(self):
        self.world.add(cand(1, 80))
        defaults = {profile.key: profile.display_name for profile in channel_module.default_profiles()}
        self.assertEqual([item.name for item in self.channels().values()], [defaults["naver_a"], defaults["naver_b"]], "아무것도 정하지 않았으면 채널 프로필의 기본 이름")
        self.world.put_profiles({"naver_a": {"display_name": "가짜 채널 에이"}, "naver_b": {"display_name": "가짜 채널 비"}})
        self.assertEqual([item.name for item in self.channels().values()], ["가짜 채널 에이", "가짜 채널 비"], "채널 프로필에 정한 이름은 런타임에 읽는다")
        support.naver_profiles(self.world.ctx, both=False)                                                  # A 만 사용자가 네이버 프로필에 이름을 정했다
        self.assertEqual([item.name for item in self.channels().values()], ["블로그 에이", "가짜 채널 비"], "사용자가 정한 이름이 먼저")

    def test_a_name_that_is_a_key_shape_is_masked_then_cut_and_an_empty_name_falls_back_to_the_service_name(self):
        self.world.add(cand(1, 80))
        self.world.put_profiles({"naver_a": {"display_name": SHORT_KEY}, "naver_b": {"display_name": "가" * 9 + " " + SHORT_KEY}})        # 파일에는 30자까지만 쓸 수 있다
        shown = self.channels()
        for item in shown.values():
            self.assertEqual(leaks(item.name, SHORT_KEY, 5), [], item.name)
            self.assertLessEqual(len(item.name), adapters.NAME_LIMIT)
        self.assertIn("가림", shown["A"].name)
        for lead in range(0, 60, 3):                                                                       # 긴 이름(서비스가 못 받는 길이)이 와도 가린 뒤에 줄인다 — 가짜 엔진으로
            engine = FakeEngine((top_channel("naver_a", name="서비스 이름"), top_channel("naver_b", name="서비스 이름")), names={"naver_a": "가" * lead + " " + KEY, "naver_b": KEY + "가" * lead})
            for item in self.channels(self.world.load(engine=engine)).values():
                self.assertEqual(leaks(item.name, KEY, 5), [], (lead, item.name))
                self.assertLessEqual(len(item.name), adapters.NAME_LIMIT)
        engine = FakeEngine((top_channel("naver_a", name="서비스 이름 에이"), top_channel("naver_b", name="서비스 이름 비")), names={"naver_a": chr(0x200B) * 3, "naver_b": "   "})
        self.assertEqual([item.name for item in self.channels(self.world.load(engine=engine)).values()], ["서비스 이름 에이", "서비스 이름 비"])
        failing = FakeEngine((top_channel("naver_a", name="서비스 이름 에이"),), names_error=RuntimeError("x"))
        shown = self.channels(self.world.load(engine=failing))
        self.assertEqual((shown["A"].name, shown["B"].name, shown["B"].state, shown["B"].enabled), ("서비스 이름 에이", "", "ok", None))      # 이름 읽기가 실패해도 구역은 산다

    def test_a_channel_with_generation_turned_off_is_read_as_off_and_has_no_rows(self):
        self.world.add(cand(1, 80), cand(2, 90, channel="naver_b"))
        self.world.put_profiles({"naver_b": {"generation_enabled": False}})
        shown = self.channels()
        self.assertEqual((shown["A"].enabled, len(shown["A"].rows)), (True, 1))
        self.assertEqual((shown["B"].enabled, shown["B"].rows, shown["B"].state), (False, (), "ok"))
        view = board_view.channel_vm(shown["B"])
        self.assertEqual(view["state"], "off")

    def test_candidates_the_service_left_out_because_their_score_does_not_match_are_counted(self):
        off = ts.make(candidate_id="tc-naver_a-seed-aaaa000000000009", channel="naver_a", language="ko", topic="예시 점수가 어긋난 글", topic_cluster="local-ai", created_at="2026-11-10T00:00:00Z",
                      scores=ts.card(75, channel_fit=60, feasibility=80, differentiation=60, timing=80, evidence=60, monetization=80))
        self.world.add(cand(1, 90), off)
        shown = self.channels()
        self.assertEqual(([row.title for row in shown["A"].rows], shown["A"].skipped, shown["B"].skipped), (["예시 주제 1번 글"], 1, 0))
        self.assertEqual(board_view.channel_vm(shown["A"])["note"], "점수를 확인할 수 없어 뺀 후보가 1개 있어요.")

    def test_candidates_the_person_rejected_or_held_never_come_back_as_recommendations(self):
        self.world.add(cand(1, 95, work_status="REJECTED"), cand(2, 94, work_status="HOLD"), cand(3, 80))
        self.assertEqual([row.title for row in self.channels()["A"].rows], ["예시 주제 3번 글"])

    def test_the_adapter_is_read_only_whatever_state_the_store_is_in(self):
        """보관함이 없거나·비었거나·깨졌거나·있어도 — 읽는 동안 파일은 하나도 만들어지거나 바뀌지 않고, 주제 엔진의 쓰는 길은 한 번도 불리지 않는다(불리면 시험이 실패한다)."""
        writers = ((tp, ("init_topics", "generate_candidates", "cleanup_hold", "import_seeds", "restore_topics", "backup_topics", "open_for_write")), (tf, ("init_files", "save_seeds")))
        with contextlib.ExitStack() as stack:
            tripped = [name for target, names in writers for name in names if hasattr(target, name)]
            self.assertGreaterEqual(len(tripped), 5)
            for target, names in writers:
                for name in names:
                    if hasattr(target, name):                                                                  # 기준에 없는 쓰기 함수(P3b-1 이후의 것)는 있을 때만 막는다
                        stack.enter_context(mock.patch.object(target, name, side_effect=AssertionError(f"{name} 이 불렸다")))
            root = self.world.ctx.workspace.root
            for label, prepare in (("없음", lambda: None),
                                   ("0바이트", lambda: (self.world.paths.folder.mkdir(parents=True, exist_ok=True), self.world.paths.database.write_bytes(b""))),
                                   ("깨짐", lambda: self.world.paths.database.write_bytes(b"this is not a database " * 200)),
                                   ("있음", lambda: (self.world.paths.database.unlink(), self.world.add(cand(1, 80), cand(2, 90, channel="naver_b"))))):
                prepare()
                before = support.tree_snapshot(root)
                data = self.world.load()
                self.assertEqual(support.tree_snapshot(root), before, label)
                self.assertEqual(len(data.board.channels), 2, label)
            self.assertEqual([len(item.rows) for item in data.board.channels], [1, 1])


class DraftsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.world = World(self.tmp.name)

    def drafts(self, **kwargs):
        return self.world.load(engine=FakeEngine(), **kwargs).board.drafts

    def test_only_unapproved_posts_are_drafts_and_each_has_a_stage_title_and_edit_time(self):
        first = self.world.draft("검토할 글", naver_a="generated", naver_b="review", updated="2026-11-05T01:00:00Z")      # 한 글에 검토 필요가 하나라도 있으면 검토 필요
        second = self.world.draft("방금 만든 초안", naver_a="generated", updated="2026-11-06T02:10:00Z")
        projects.new_project(self.world.ctx, "아직 시작 안 한 글", support.ko_text())                         # 모든 플랫폼이 시작 전 — 초안이 아니다
        approved = support.make_approved(self.world.ctx)                                                      # 승인까지 끝난 글 — 승인 전이 아니다
        shown = self.drafts()
        self.assertEqual(shown.state, "ok")
        self.assertEqual([(row.id, row.title, row.stage, row.updated, row.sample) for row in shown.rows],
                         [(second, "방금 만든 초안", "generated", "2026-11-06T02:10:00Z", False), (first, "검토할 글", "review", "2026-11-05T01:00:00Z", False)])
        self.assertNotIn(approved, [row.id for row in shown.rows])
        self.assertEqual(shown.skipped, 0)

    def test_a_post_with_a_draft_on_one_blog_and_an_approved_page_is_still_a_draft(self):
        view = projects.new_project(self.world.ctx, "섞인 글", support.ko_text())
        with self.world.ctx.store() as store:
            project = store.load(view.project_id)
            project.transition("naver_b", st.DRAFT_GENERATED, now="2026-11-05T05:00:00Z")
            store.save(project)
        self.assertEqual([(row.id, row.stage) for row in self.drafts().rows], [(view.project_id, "generated")])

    def test_at_most_five_come_back_the_most_recently_edited_first(self):
        ids = [self.world.draft(f"초안 {number:02d}", naver_a="review", updated=f"2026-11-{number:02d}T00:00:00Z") for number in range(1, 13)]
        shown = self.drafts()
        self.assertEqual([row.title for row in shown.rows], ["초안 12", "초안 11", "초안 10", "초안 09", "초안 08"])
        self.assertEqual([row.id for row in shown.rows], ids[::-1][:5])

    def test_no_posts_store_is_a_normal_empty_list_and_nothing_is_created(self):
        before = support.tree_snapshot(self.world.ctx.workspace.root)
        shown = self.drafts()
        self.assertEqual((shown.state, shown.rows, shown.skipped, shown.failure), ("ok", (), 0, None))
        self.assertFalse(self.world.ctx.workspace.store_path.exists())
        self.assertEqual(support.tree_snapshot(self.world.ctx.workspace.root), before)

    def test_a_post_that_cannot_be_read_is_skipped_and_counted_not_fatal(self):
        rows = [projects.ProjectRow("p1", "읽은 초안", 1, "2026-11-05T00:00:00Z", {"naver_a": st.REVIEW_REQUIRED}, ""), projects.ProjectRow("p2", "못 읽은 글", 1, "2026-11-06T00:00:00Z", {}, "CONTENT_INVALID"),
                projects.ProjectRow("p3", "또 못 읽은 글", 1, "2026-11-07T00:00:00Z", {}, "CONTENT_INVALID")]
        with mock.patch.object(adapters.project_service, "list_projects", lambda ctx: rows):
            shown = self.drafts()
        self.assertEqual(([(row.id, row.stage) for row in shown.rows], shown.skipped, shown.state), ([("p1", "review")], 2, "ok"))
        view = board_view.list_vm(shown, board_view.draft_vm, board_view.DRAFT_TEXTS)
        self.assertEqual(view["note"], "읽지 못해 건너뛴 글이 2개 있어요.")

    def test_a_post_list_that_cannot_be_read_fails_only_the_drafts_and_leaves_the_counts_unknown(self):
        def boom(ctx):
            raise AppError("DATA_DIR_UNSAFE", {"경로": "C:" + chr(92) + "데이터"}, detail="세부 " + KEY)

        self.world.add(cand(1, 80))
        with mock.patch.object(adapters.project_service, "list_projects", boom):
            data = self.world.load()
        self.assertEqual((data.done, data.pub), (None, None))
        self.assertEqual((data.board.drafts.state, data.board.drafts.rows, data.board.drafts.failure.code), ("failed", (), "DATA_DIR_UNSAFE"))
        self.assertEqual(leaks(data.board.drafts.failure.user_message, KEY, 5), [])                         # 세부(detail)의 키는 문장에 없다
        self.assertEqual(len(data.board.channels[0].rows), 1, "추천 구역은 그대로 읽힌다")
        view = app_state.AppState(self.world.provider())
        view.apply_home(data)
        kpis = {item["key"]: item["state"] for item in view.home_view()["board"]["kpi"]}
        self.assertEqual((kpis["done"], kpis["pub"]), ("before_count", "before_count"))                      # 못 센 수는 0 이 아니라 집계 전

    def test_titles_are_handed_over_whole_so_that_only_the_view_model_masks_then_cuts(self):
        rows = [projects.ProjectRow("p1", "가" * 150 + " " + KEY, 1, "2026-11-05T00:00:00Z", {"naver_a": st.DRAFT_GENERATED}, "")]
        with mock.patch.object(adapters.project_service, "list_projects", lambda ctx: rows):
            shown = self.drafts()
        self.assertEqual(shown.rows[0].title, "가" * 150 + " " + KEY)
        view = board_view.draft_vm(shown.rows[0], 1)
        self.assertEqual(leaks(view["title"] + view["a11y"], KEY, 5), [])

    def test_the_draft_helpers_by_hand_written_values(self):
        self.assertEqual(adapters.STAGE_OF, {st.DRAFT_GENERATED: "generated", st.REVIEW_REQUIRED: "review"})
        for statuses, stage in (({}, None), ({"naver_a": st.NOT_STARTED}, None), ({"naver_a": st.APPROVED, "github_pages": st.PUBLISHED}, None), ({"naver_a": st.PUBLISH_FAILED}, None),
                                ({"naver_a": st.DRAFT_GENERATED}, "generated"), ({"naver_a": st.REVIEW_REQUIRED}, "review"), ({"naver_a": st.DRAFT_GENERATED, "naver_b": st.REVIEW_REQUIRED}, "review"),
                                ({"naver_a": st.DRAFT_GENERATED, "github_pages": st.APPROVED}, "generated")):
            self.assertEqual(adapters.draft_stage(statuses), stage, statuses)
        rows = [SimpleNamespace(updated_at=at, project_id=pid) for at, pid in (("2026-11-05T00:00:00Z", "a"), ("2026-11-06T00:00:00Z", "b"), ("2026-11-06T00:00:00Z", "c"), ("2026-11-04T00:00:00Z", "d"))]
        self.assertEqual([row.project_id for row in adapters.newest_first(rows)], ["c", "b", "a", "d"])


class RecentPublishedTest(unittest.TestCase):
    """최근 발행 — 서비스 목록에 발행한 때가 없어 글마다 읽는 임시 방식(운영자 2026-11-06 확인 요청 004 의 답 6): 한 글의 실패가 구역을 막지 않고·시간 제한이 있고·`updated_at` 을 발행일로 쓰지 않고·모르면 '발행일 확인 불가'."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.world = World(self.tmp.name)

    def recent(self, rows=None, show=None, **kwargs):
        """가짜 글 목록(`rows`)과 가짜 읽기(`show`)로 최근 발행 구역을 읽는다 — `rows` 가 없으면 진짜 글 보관함."""
        provider = self.world.provider(engine=FakeEngine(), show_project=show, **kwargs)
        if rows is None:
            return provider.load_home(lambda *a: None, NO_STATE).board.recent
        with mock.patch.object(adapters.project_service, "list_projects", lambda ctx: rows):
            return provider.load_home(lambda *a: None, NO_STATE).board.recent

    def test_the_published_date_is_read_post_by_post_and_the_latest_platform_wins(self):
        first = published(self.world, "두 곳에 발행", {"naver_a": "2026-11-01T02:00:00Z", "naver_b": "2026-11-03T05:00:00Z"}, updated="2026-11-04T00:00:00Z")
        second = published(self.world, "한 곳에 발행", {"github_pages": "2026-10-20T00:00:00Z"}, updated="2026-11-05T00:00:00Z")
        published(self.world, "아직 발행 전", {}, updated="2026-11-06T00:00:00Z")
        shown = self.recent()
        self.assertEqual((shown.state, shown.skipped), ("ok", 0))
        self.assertEqual([(row.id, row.title, row.published, row.sample) for row in shown.rows],
                         [(first, "두 곳에 발행", "2026-11-03T05:00:00Z", False), (second, "한 곳에 발행", "2026-10-20T00:00:00Z", False)])     # 발행한 때가 늦은 순(고친 때는 반대여도)

    def test_the_post_list_and_every_post_read_get_a_read_only_context(self):
        """독립 검증 L2 — 글 목록과 글마다 읽기에 넘기는 문맥은 읽기 전용(`read_only_store`)이어야 글 보관함을 만들지도 올리지도 않는다 — 소스 문자열이 아니라 실제로 받은 문맥으로 확인한다."""
        rows = [row_for("p1", "발행한 글", "2026-11-06T00:00:00Z", {"naver_a": st.PUBLISHED_MANUAL}), row_for("p2", "또 발행한 글", "2026-11-05T00:00:00Z", {"naver_a": st.PUBLISHED_MANUAL})]
        listed, shown_to = [], []

        def listing(ctx):
            listed.append(ctx.read_only_store)
            return rows

        def look(ctx, project_id):
            shown_to.append((project_id, ctx.read_only_store))
            return SimpleNamespace(variants=())

        provider = self.world.provider(engine=FakeEngine(), show_project=look)
        with mock.patch.object(adapters.project_service, "list_projects", listing):
            provider.load_home(lambda *a: None, NO_STATE)
        self.assertEqual(listed, [True])
        self.assertEqual(shown_to, [("p1", True), ("p2", True)])

    def test_the_last_edit_time_is_never_taken_for_the_published_date(self):
        published(self.world, "나중에 고친 글", {"naver_a": "2026-10-01T00:00:00Z"}, updated="2026-12-01T00:00:00Z")
        self.assertEqual([row.published for row in self.recent().rows], ["2026-10-01T00:00:00Z"])         # 고친 때(12월)가 아니라 발행한 때(10월)
        rows = [row_for("p1", "읽지 못하는 글", "2026-12-01T00:00:00Z", {"naver_a": st.PUBLISHED_MANUAL})]

        def refuse(ctx, project_id):
            raise AppError("CONTENT_NOT_FOUND", {"항목": project_id})

        shown = self.recent(rows, show=refuse)
        self.assertEqual([(row.title, row.published) for row in shown.rows], [("읽지 못하는 글", None)])    # 고친 때가 있어도 날짜는 모른다
        view = board_view.recent_vm(shown.rows[0], 1)
        self.assertEqual((view["date"], view["date_text"], view["known"]), ("", "발행일 확인 불가", False))
        self.assertNotIn("2026-12", repr(view))
        self.assertEqual({field.name for field in dataclasses.fields(services.RecentRow)}, {"id", "title", "published", "sample"}, "고친 때를 담을 칸 자체가 없다")

    def test_a_published_post_without_a_stamp_is_unknown_not_guessed(self):
        view = SimpleNamespace(variants=(SimpleNamespace(platform="naver_a", status=st.PUBLISHED_MANUAL, published_at=None), SimpleNamespace(platform="naver_b", status=st.READY_TO_COPY, published_at="2026-11-02T00:00:00Z"),
                                         SimpleNamespace(platform="github_pages", status=st.PUBLISHED, published_at="")))
        rows = [row_for("p1", "시각 없는 글", "2026-11-05T00:00:00Z", {"naver_a": st.PUBLISHED_MANUAL})]
        shown = self.recent(rows, show=lambda ctx, project_id: view)
        self.assertEqual([row.published for row in shown.rows], [None])                                    # 발행 전 플랫폼의 시각이나 빈 글은 쓰지 않는다

    def test_one_post_that_fails_to_read_never_blocks_the_others_and_nothing_of_the_failure_is_shown(self):
        rows = [row_for(f"p{number}", f"글 {number}", f"2026-11-0{number}T00:00:00Z", {"naver_a": st.PUBLISHED_MANUAL}) for number in (1, 2, 3)]
        stamps = {"p1": "2026-10-01T00:00:00Z"}

        def show(ctx, project_id):
            if project_id == "p2":
                raise AppError("CONTENT_INVALID", {"항목": "글"}, detail="세부 " + KEY)
            if project_id == "p3":
                raise RuntimeError("내부 " + SECRET_PATH + " " + KEY)
            return SimpleNamespace(variants=(SimpleNamespace(platform="naver_a", status=st.PUBLISHED_MANUAL, published_at=stamps[project_id]),))

        shown = self.recent(rows, show=show)
        self.assertEqual((shown.state, shown.skipped, shown.failure), ("ok", 0, None))
        self.assertEqual([(row.id, row.published) for row in shown.rows], [("p1", "2026-10-01T00:00:00Z"), ("p3", None), ("p2", None)])      # 아는 글이 앞, 모르는 글은 뒤(고친 때 순서 그대로)
        self.assertEqual(leaks(repr(shown), KEY, 5), [])
        self.assertNotIn("비밀폴더", repr(shown))

    def test_a_slow_read_is_given_up_after_the_time_limit_and_the_other_posts_are_still_read(self):
        rows = [row_for(f"p{number}", f"글 {number}", f"2026-11-0{number}T00:00:00Z", {"naver_a": st.PUBLISHED_MANUAL}) for number in (1, 2, 3)]
        called = []

        def show(ctx, project_id):
            called.append(project_id)
            if project_id == "p2":
                time.sleep(2.0)                                                                             # 제한(0.05초)보다 훨씬 오래 걸린다(끝까지 기다리는 구현이면 2초 이상)
            return SimpleNamespace(variants=(SimpleNamespace(platform="naver_a", status=st.PUBLISHED_MANUAL, published_at=f"2026-10-0{project_id[1]}T00:00:00Z"),))

        started = time.monotonic()
        shown = self.recent(rows, show=show, recent_timeout=0.05, recent_budget=10)
        elapsed = time.monotonic() - started
        self.assertLess(elapsed, 1.5, "느린 글을 끝까지 기다리지 않는다")
        self.assertEqual(sorted(called), ["p1", "p2", "p3"], "느린 글 뒤의 글도 읽는다")
        self.assertEqual([(row.id, row.published) for row in shown.rows], [("p3", "2026-10-03T00:00:00Z"), ("p1", "2026-10-01T00:00:00Z"), ("p2", None)])

    def test_the_whole_time_budget_stops_further_reads_and_leaves_the_rest_unknown(self):
        rows = [row_for(f"p{number}", f"글 {number}", f"2026-11-0{number}T00:00:00Z", {"naver_a": st.PUBLISHED_MANUAL}) for number in (1, 2, 3, 4)]
        called, ticks = [], iter(x * 2.5 for x in range(100))                                              # 시계가 한 번 볼 때마다 2.5초씩 간다

        def show(ctx, project_id):
            called.append(project_id)
            return SimpleNamespace(variants=(SimpleNamespace(platform="naver_a", status=st.PUBLISHED_MANUAL, published_at="2026-10-01T00:00:00Z"),))

        shown = self.recent(rows, show=show, recent_budget=4.0, monotonic=lambda: next(ticks))
        self.assertEqual(called, ["p4"], "시작 2.5초 뒤 첫 글만 읽고(남은 1.5초) 그 뒤는 예산이 바닥나 읽지 않는다")
        self.assertEqual([(row.id, row.published) for row in shown.rows], [("p4", "2026-10-01T00:00:00Z"), ("p3", None), ("p2", None), ("p1", None)])

    def test_at_most_five_posts_are_read_and_they_are_the_most_recently_edited_published_ones(self):
        rows = [row_for(f"p{number:02d}", f"글 {number}", f"2026-11-{number:02d}T00:00:00Z", {"naver_a": st.PUBLISHED_MANUAL}) for number in range(1, 13)]
        rows.append(row_for("draft", "초안", "2026-11-30T00:00:00Z", {"naver_a": st.REVIEW_REQUIRED}))      # 가장 최근에 고쳤지만 발행 전 — 읽지 않는다
        called = []

        def show(ctx, project_id):
            called.append(project_id)
            return SimpleNamespace(variants=(SimpleNamespace(platform="naver_a", status=st.PUBLISHED_MANUAL, published_at="2026-10-" + project_id[1:] + "T00:00:00Z"),))

        shown = self.recent(rows, show=show)
        self.assertEqual(called, ["p12", "p11", "p10", "p09", "p08"])
        self.assertEqual([row.id for row in shown.rows], ["p12", "p11", "p10", "p09", "p08"])

    def test_no_published_posts_or_no_posts_store_is_a_normal_empty_list_that_reads_nothing(self):
        def never(ctx, project_id):
            raise AssertionError("읽을 글이 없는데 글을 읽었다")

        before = support.tree_snapshot(self.world.ctx.workspace.root)
        shown = self.recent(show=never)
        self.assertEqual((shown.state, shown.rows, shown.skipped, shown.failure), ("ok", (), 0, None))
        self.assertFalse(self.world.ctx.workspace.store_path.exists())
        self.assertEqual(support.tree_snapshot(self.world.ctx.workspace.root), before)
        only_draft = self.recent([row_for("p1", "초안", "2026-11-05T00:00:00Z", {"naver_a": st.DRAFT_GENERATED})], show=never)
        self.assertEqual(only_draft.rows, ())

    def test_posts_that_cannot_be_listed_are_skipped_and_counted_and_a_list_failure_fails_only_this_section(self):
        rows = [row_for("p1", "읽은 글", "2026-11-05T00:00:00Z", {"naver_a": st.PUBLISHED_MANUAL}), row_for("p2", "못 읽은 글", "2026-11-06T00:00:00Z", {}, "CONTENT_INVALID")]
        shown = self.recent(rows, show=lambda ctx, project_id: SimpleNamespace(variants=()))
        self.assertEqual(([row.id for row in shown.rows], shown.skipped), (["p1"], 1))

        def boom(ctx):
            raise AppError("DATA_DIR_UNSAFE", {"경로": "C:" + chr(92) + "데이터"}, detail=KEY)

        with mock.patch.object(adapters.project_service, "list_projects", boom):
            data = self.world.provider(engine=FakeEngine()).load_home(lambda *a: None, NO_STATE)
        self.assertEqual((data.board.recent.state, data.board.recent.rows, data.board.recent.failure.code), ("failed", (), "DATA_DIR_UNSAFE"))
        self.assertEqual((data.board.drafts.state, data.board.channels[0].state), ("failed", "ok"))
        self.assertEqual(leaks(repr(data.board.recent), KEY, 5), [])

    def test_a_cancel_while_reading_the_posts_stops_without_reading_the_next_one(self):
        rows = [row_for(f"p{number}", f"글 {number}", f"2026-11-0{number}T00:00:00Z", {"naver_a": st.PUBLISHED_MANUAL}) for number in (1, 2, 3)]
        called, state = [], {"n": 0}

        def show(ctx, project_id):
            called.append(project_id)
            state["armed"] = True
            return SimpleNamespace(variants=())

        def cancelled():
            return state.get("armed", False)                                                               # 첫 글을 읽은 뒤부터 취소

        provider = self.world.provider(engine=FakeEngine(), show_project=show)
        with mock.patch.object(adapters.project_service, "list_projects", lambda ctx: rows):
            with self.assertRaises(jobs.JobCancelled):
                provider.load_home(lambda *a: None, cancelled)
        self.assertEqual(called, ["p3"], "취소한 뒤에는 다음 글을 읽지 않는다")

    def test_a_cancel_pressed_while_the_last_post_is_being_read_still_stops_the_load_and_gives_no_result(self):
        """글 사이의 취소 확인은 마지막 글을 읽는 동안 누른 취소를 못 본다 — 읽기가 끝난 뒤의 마지막 확인이 그것을 잡는다(변이 점검: 이 확인을 지우면 시험이 통과했다)."""
        rows = [row_for(f"p{number}", f"글 {number}", f"2026-11-0{number}T00:00:00Z", {"naver_a": st.PUBLISHED_MANUAL}) for number in (1, 2)]
        called = []

        def show(ctx, project_id):
            called.append(project_id)
            return SimpleNamespace(variants=())

        def cancelled():
            return len(called) == 2                                                                         # 두 번째(마지막) 글을 읽은 뒤부터 취소 — 글을 읽기 전의 확인은 모두 '아니오'

        provider = self.world.provider(engine=FakeEngine(), show_project=show)
        with mock.patch.object(adapters.project_service, "list_projects", lambda ctx: rows):
            with self.assertRaises(jobs.JobCancelled):
                provider.load_home(lambda *a: None, cancelled)
        self.assertEqual(called, ["p2", "p1"], "두 글을 모두 읽은 뒤에 취소가 먹었다")

    def test_the_real_service_read_is_the_default_and_it_only_reads(self):
        first = published(self.world, "실제 읽기 하나", {"naver_a": "2026-11-02T01:30:00Z"}, updated="2026-11-04T00:00:00Z")
        published(self.world, "실제 읽기 둘", {"github_pages": "2026-11-05T15:00:00Z"}, updated="2026-11-03T00:00:00Z")
        before = support.tree_snapshot(self.world.ctx.workspace.root)
        data = self.world.provider(engine=FakeEngine()).load_home(lambda *a: None, NO_STATE)
        self.assertEqual(support.tree_snapshot(self.world.ctx.workspace.root), before, "읽는 동안 파일이 하나도 바뀌지 않는다")
        self.assertEqual([(row.title, row.published) for row in data.board.recent.rows], [("실제 읽기 둘", "2026-11-05T15:00:00Z"), ("실제 읽기 하나", "2026-11-02T01:30:00Z")])
        self.assertEqual(data.pub, 2)                                                                       # 옛 발행 완료 수도 같은 글 목록에서
        state = app_state.AppState(self.world.provider(engine=FakeEngine()))
        state.apply_home(data)
        shown = state.home_view()["board"]["recent"]
        self.assertEqual([(row["title"], row["date_text"]) for row in shown["rows"]], [("실제 읽기 둘", "2026-11-06"), ("실제 읽기 하나", "2026-11-02")])      # 한국 날짜(UTC 15시 → 다음 날)
        self.assertNotIn(first, repr(shown))

    def test_the_limits_are_the_documented_values_and_each_post_gets_less_time_than_the_whole(self):
        self.assertEqual((adapters.RECENT_TIMEOUT, adapters.RECENT_BUDGET, services.HOME_LIMIT), (1.5, 4.0, 5))
        self.assertLess(adapters.RECENT_TIMEOUT, adapters.RECENT_BUDGET)


class LoadHomeBoardTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.world = World(self.tmp.name)

    def test_the_post_list_is_read_once_per_load_and_only_the_published_posts_are_read_again(self):
        """글 목록은 불러올 때마다 한 번만 읽는다(옛 완료·발행 수와 새 구역이 같은 목록을 쓴다) — 발행한 글을 글마다 다시 읽는 것은 많아야 다섯 편."""
        for number in range(1, 8):
            published(self.world, f"발행 글 {number}", {"naver_a": f"2026-10-0{number}T00:00:00Z"}, updated=f"2026-11-0{number}T00:00:00Z")
        self.world.draft("초안 하나", naver_a="review")
        with mock.patch.object(adapters.project_service, "list_projects", wraps=adapters.project_service.list_projects) as listing, \
                mock.patch.object(adapters.project_service, "show_project", wraps=adapters.project_service.show_project) as showing:
            data = self.world.load(engine=FakeEngine())
        self.assertEqual((listing.call_count, showing.call_count), (1, 5))
        self.assertEqual((data.done, data.pub, len(data.board.recent.rows), len(data.board.drafts.rows)), (7, 7, 5, 1))      # 발행한 글도 작성 완료로 센다(옛 규칙 그대로)

    def test_the_old_home_data_is_read_exactly_as_before_and_the_board_rides_along(self):
        support.naver_profiles(self.world.ctx)
        svc_candidates = __import__("chanceblog_desktop.service.candidates", fromlist=["x"])
        svc_candidates.add_candidate(self.world.ctx, topic="옛 후보", keyword="옛 키워드", blogs=("naver_a",))
        self.world.add(cand(1, 88))
        support.make_approved(self.world.ctx)
        data = self.world.load()
        self.assertEqual(([topic.title for topic in data.topics], [(blog.key, blog.name, blog.candidates) for blog in data.blogs], data.done, data.pub, data.sample), (["옛 후보"], [("A", "블로그 에이", 1), ("B", "블로그 비", 0)], 1, 0, False))
        self.assertIsInstance(data.board, services.BoardData)
        self.assertEqual([item.key for item in data.board.channels], ["A", "B"])
        self.assertEqual([row.title for row in data.board.channels[0].rows], ["예시 주제 1번 글"])
        self.assertFalse(data.board.sample)

    def test_the_provider_stays_a_home_provider_and_the_engine_is_replaceable(self):
        provider = self.world.provider()
        self.assertIsInstance(provider, services.HomeProvider)
        self.assertIsInstance(provider._engine, adapters.ServiceEngine)
        fake = FakeEngine()
        self.assertIs(self.world.provider(engine=fake)._engine, fake)

    def test_the_whole_home_view_model_works_on_the_real_adapter_data_and_is_not_marked_as_example(self):
        self.world.add(cand(1, 90, trend_status="rising", **TREND), cand(2, 70, cluster="x-1"), cand(3, 85, channel="naver_b"))
        self.world.draft("초안", naver_a="review", updated="2026-11-06T02:10:00Z")
        state = app_state.AppState(self.world.provider())
        state.apply_home(self.world.load())
        board = state.home_view()["board"]
        self.assertEqual((board["state"], board["sample"]), ("ready", False))
        self.assertEqual([(item["state"], item["count"]) for item in board["recommend"]], [("normal", 2), ("normal", 1)])
        self.assertEqual([row["score_text"] for row in board["recommend"][0]["rows"]], ["90", "70"])
        self.assertEqual([row["interest"]["label"] for row in board["recommend"][0]["rows"]], ["관심도 상승", "관심도 데이터 부족"])
        self.assertTrue(all(row["delta"] is None for item in board["recommend"] for row in item["rows"]), "이전 점수를 알 수 없어 변화량은 숨긴다")
        self.assertEqual([(row["title"], row["stage_label"], row["time"]) for row in board["drafts"]["rows"]], [("초안", "검토 필요", "2026-11-06 11:10")])
        self.assertTrue(all(not row["sample"] for item in board["recommend"] for row in item["rows"]))
        kpis = {item["key"]: item["text"] for item in board["kpi"]}
        self.assertEqual((kpis["topics"], kpis["done"], kpis["pub"], kpis["ideas"]), ("3개", "0개", "0개", "0개"))

    def test_no_data_at_all_gives_normal_empty_sections_and_a_not_connected_recommended_count(self):
        data = self.world.load()
        self.assertEqual((data.topics, data.done, data.pub), ((), 0, 0))
        board = app_state.AppState(self.world.provider())
        board.apply_home(data)
        shown = board.home_view()["board"]
        self.assertEqual([item["state"] for item in shown["recommend"]] + [shown["drafts"]["state"]], ["empty", "empty", "empty"])
        self.assertEqual({item["key"]: (item["text"], item["state"]) for item in shown["kpi"]}["topics"], ("연결 전", "before_connect"))      # 보관함이 아직 없다 — 0 이라고 하지 않는다

    def test_every_cancel_check_raises_a_cancel_and_the_engine_is_not_read_after_a_cancel(self):
        self.world.add(cand(1, 80))
        counter = {"n": 0}

        def never():
            counter["n"] += 1
            return False

        self.world.load(cancelled=never, engine=FakeEngine())
        total = counter["n"]
        self.assertGreaterEqual(total, 4)                                                                   # 옛 두 곳 + 새 구역 사이
        for stop_at in range(1, total + 1):
            engine, seen = FakeEngine(), {"n": 0}

            def cancelled(stop_at=stop_at, seen=seen):
                seen["n"] += 1
                return seen["n"] >= stop_at

            with self.assertRaises(jobs.JobCancelled, msg=f"{stop_at}번째에서 취소"):
                self.world.load(cancelled=cancelled, engine=engine)
            if stop_at <= 2:
                self.assertEqual(engine.calls, [], "옛 단계에서 취소하면 새 구역은 읽지 않는다")

    def test_the_source_of_the_new_reads_names_no_writer_of_the_service(self):
        source = (ROOT / "src" / "chanceblog_desktop" / "ui" / "adapters.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        parts = {node.name: ast.get_source_segment(source, node) for node in tree.body if isinstance(node, ast.ClassDef) and node.name in ("ServiceEngine", "ServiceHomeProvider", "Counts")}
        self.assertEqual(set(parts), {"ServiceEngine", "ServiceHomeProvider", "Counts"})
        for name, body in parts.items():
            for forbidden in ("add_candidates", "open_for_write", "generate_candidates", "init_topics", "init_files", "cleanup_hold", "import_seeds", "restore_topics", "backup_topics", "save_seeds",
                              "write_json", "write_text", "write_bytes", ".save(", ".put(", ".delete(", ".unlink(", "mkdir(", "remove(", "rename(", "open("):
                self.assertNotIn(forbidden, body, f"{name}: {forbidden}")
        engine = parts["ServiceEngine"]
        used = set(re.findall(r"\b(?:topic_service|topic_files)\.(\w+)", engine))
        self.assertEqual(used, {"top_candidates", "load_profiles", "topic_paths"}, "주제 엔진은 읽는 함수 셋만 부른다")
        self.assertNotIn("reading_only", engine)
        self.assertEqual(len(re.findall(r"project_service\.list_projects\(ctx\.reading_only\(\)\)", parts["ServiceHomeProvider"])), 1)

    def test_an_internal_candidate_number_never_reaches_the_view_model_texts(self):
        self.world.add(cand(1, 80))
        state = app_state.AppState(self.world.provider())
        state.apply_home(self.world.load())
        flat = texts_of(state.home_view()["board"])
        self.assertNotIn("tc-naver_a", flat)


class ConnectionsUnchangedTest(unittest.TestCase):
    def test_the_connections_provider_is_the_same_as_before_and_shares_the_data_folder(self):
        provider = adapters.ServiceHomeProvider("~/폴더 없음", engine=FakeEngine())
        paired = provider.connections_provider()
        self.assertIsInstance(paired, adapters.ServiceConnectionsProvider)
        self.assertEqual(paired._data_dir, "~/폴더 없음")


if __name__ == "__main__":
    unittest.main()
