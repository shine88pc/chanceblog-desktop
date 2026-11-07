"""Seed 관리 쓰기(`service/seed_manage.py` — 변경 등급 T2) 시험. **전부 임시 폴더**(이 PC 의 실제 데이터 폴더에는 쓰지 않는다). 네트워크·실제 시계·키 보관소 없이 돈다. 씨앗은 모두 시험용 예시다(실제 목록이 아니다).

지키는 것:
  1) 읽기: 파일이 없으면 빈 목록(파일도 폴더도 만들지 않는다)·0바이트도 '아직 없음'·틀린 파일은 고치거나 덮어쓰지 않고 멈춘다·판 1 파일도 읽는다·180일 제안은 보이기만 하고 아무것도 바꾸지 않는다.
  2) 상태 바꾸기: `TRANSITIONS` 만(되돌릴 수 없는 전환은 거절)·사용 중이 되면 사용 시작일이 기준일·바뀐 것은 그 씨앗 하나뿐이다. **여러 개를 한꺼번에**는 확인 표시(진짜 `True`)와 확인한 개수가 있어야 하고 **전부 바뀌거나 하나도 안 바뀐다**.
  3) 고치기·새로 등록·제안 불러오기: 고칠 수 있는 칸만·새 씨앗은 **늘 승인 전**(사용 중으로 등록하는 길 없음)·번호는 서비스가 정한다·같은 소속의 같은 낱말은 거절·키 모양 글은 쓰기 전에 거른다. 씨앗이 파일에서 사라지는 길은 없다.
  4) **승인 전 씨앗이 후보 생성에 새지 않는다**: 등록·불러오기 뒤에도 후보 계획에 그 씨앗에서 나온 후보가 하나도 없고, 승인한 씨앗에서만 나오며 다시 쉬게 하면 다시 빠진다.
  5) **쓰기 안전**(실패 주입 — 진짜 `os` 호출에 끼워 넣는다): 백업 쓰는 중·본 파일 임시 파일 쓰는 중·디스크에 내려보내기·이름 바꾸기 직전·직후 읽기 검증 실패·백업 실패·읽기 전용·디스크 가득·낡은 판·다른 창이 쥔 잠금에서
     **기존 값이 한 바이트도 안 바뀌거나(되돌림) 직전 내용으로 돌아가고**, 임시 파일·잠금 파일이 남지 않으며, 같은 일을 다시 하면 된다. 안전망(`_guard`)은 코드 실수로 승인하지 않은 상태 변경·승인 전이 아닌 새 씨앗·사라지는 씨앗·허락되지 않은 칸 변경이 생겨도 쓰지 않는다.
  6) 동시 저장: 같은 읽기에서 출발한 두 저장 중 하나만 저장되고 다른 하나는 낡은 판이나 잠금으로 물러난다 · 진짜 프로세스 둘이 서로 다른 씨앗을 번갈아 저장해도 마지막 값이 모두 남는다.
  7) 쓰기가 닿는 곳은 `seeds.json`·`.bak`·`.v1.bak`·잠금뿐이다(다른 파일은 바이트까지 그대로) · 소스에 낮은 수준 쓰기 호출이 없고 실제 씨앗 목록·블로그 이름이 저장소 어디에도 없다.
"""
import contextlib
import dataclasses
import errno
import json
import os
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import service_support as ss  # noqa: E402
import topics_support as ts  # noqa: E402
from test_service_topics import TODAY as PLAN_DAY  # noqa: E402
from test_service_topics import World  # noqa: E402
from test_topics_seeds_v2 import proposal, proposal_file  # noqa: E402

from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.service import seed_manage as sm  # noqa: E402
from chanceblog_desktop.service import topic_files as tf  # noqa: E402
from chanceblog_desktop.topics import channels, layout, seeds as sd  # noqa: E402

ROOT = ss.ROOT
DAY = "2026-11-02"                                   # `make_ctx` 의 가짜 시계가 가리키는 한국 날짜
KEY_SHAPED = "AK" + "IA" + "ABCDEFGHIJKLMNOP"        # 키 모양의 가짜 값(조각으로 나눠 적어 저장소에 키 문자열이 없다)
REAL = {name: getattr(os, name) for name in ("open", "write", "fsync", "close", "replace")}


def code_of(call, *args, **kwargs):
    try:
        call(*args, **kwargs)
    except AppError as error:
        return error.code
    return None


def seed(seed_id="ex-1", **changes):
    """승인 전 예시 씨앗(네이버 A 전용) — 바꿀 칸만 이름으로 준다."""
    values = {"seed_id": seed_id, "keyword": f"예시 낱말 {seed_id}", "state": "proposed", "scope": "naver_a"}
    values.update(changes)
    return ts.example_seed(**values)


def active(seed_id="ex-9", **changes):
    values = {"state": "active", "active_since": "2026-10-01"}
    values.update(changes)
    return seed(seed_id, **values)


def three():
    return [seed("ex-1"), seed("ex-2"), seed("ex-3", scope="common", keyword="예시 공통 낱말")]


def create_fields(**changes):
    values = {"keyword": "예시 새 낱말", "major": "예시 대분류", "minor": "예시 중분류", "seed_type": "general", "target_type": "product", "scope": "naver_a"}
    values.update(changes)
    return values


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.ctx = ss.make_ctx(tmp.name)
        self.paths = tf.topic_paths(self.ctx.workspace)
        self.root = Path(self.ctx.workspace.root)

    def snap(self):
        return sm.read_snapshot(self.ctx)

    def by_id(self, snap=None):
        return {item.seed_id: item for item in (snap or self.snap()).seeds}

    def bytes_of(self, path=None):
        path = path or self.paths.seeds
        return path.read_bytes() if path.exists() else None

    def tree(self):
        return ss.tree_snapshot(self.root)

    def listing(self):
        return sorted(str(path) for path in self.tmp.rglob("*"))

    def leftovers(self):
        """남으면 안 되는 것 — 임시 파일(`*.tmp`)과 잠금 파일."""
        return sorted(path.relative_to(self.root).as_posix() for path in self.root.rglob("*") if path.is_file() and (path.name.endswith(".tmp") or path.name.endswith(".lock")))

    def put(self, items, *, schema=None):
        """파일을 미리 만들어 둔다 — 사람이 JSON 을 고친 것처럼 서비스를 거치지 않고 쓴다."""
        data = sd.seeds_to_dict(items)
        if schema == 1:
            data["schema"] = 1
            data["seeds"] = [{name: value for name, value in item.items() if name in sd._KEYS_V1} for item in data["seeds"]]
        self.paths.folder.mkdir(parents=True, exist_ok=True)
        self.paths.seeds.write_bytes((json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"))

    def state(self, seed_id, new_state, version=None):
        return sm.set_state(self.ctx, seed_id, new_state, expected_version=self.snap().version if version is None else version, today=DAY)


# ---- 규칙(순수) --------------------------------------------------------------------------------------------------------------------
class RulesTest(unittest.TestCase):
    def test_the_next_manual_number_follows_the_biggest_one_and_never_uses_chance(self):
        self.assertEqual(sm.next_id(()), "M001")
        self.assertEqual(sm.next_id([seed("S010"), seed("ex-1")]), "M001", "수동 번호가 아닌 번호는 세지 않는다")
        self.assertEqual(sm.next_id([seed("M001"), seed("M007"), seed("S100")]), "M008")
        self.assertEqual(sm.next_id([seed("M999")]), "M1000")
        self.assertEqual(sm.next_id([seed("M003"), seed("M001")]), "M004", "빠진 번호(M002)를 다시 쓰지 않는다")
        again = sm.next_id([seed("M002")])
        self.assertEqual(again, sm.next_id([seed("M002")]), "같은 입력이면 같은 번호(난수 없음)")

    def test_the_editable_and_create_fields_are_real_seed_fields_and_never_the_state_or_identity(self):
        names = {field.name for field in dataclasses.fields(sd.Seed)}
        self.assertLessEqual(set(sm.EDITABLE), names)
        self.assertLessEqual(set(sm.CREATE_REQUIRED) | set(sm.CREATE_OPTIONAL), names)
        forbidden = {"seed_id", "state", "active_since", "last_selected_on", "registered_on", "keyword", "major", "minor", "scope", "seed_type", "target_type", "prepare_from", "publish_from", "publish_until",
                     "peak_period", "recurrence", "seasonal_priority_state", "needs_region", "brand_case", "sponsor_tag"}
        self.assertEqual(set(sm.EDITABLE) & forbidden, set(), "고칠 수 있는 칸에 상태·번호·낱말·소속·중요도·계절 일정이 없다")
        self.assertNotIn("seasonal", sm.CREATE_SEED_TYPES)
        self.assertEqual(set(sm.CREATE_SEED_TYPES), {"general", "priority", "realtime", "sponsorable"})
        self.assertLessEqual(set(sm.TEXT_FIELDS), names)

    def test_apply_fields_names_every_wrong_field_and_accepts_only_the_editable_ones(self):
        base = seed(scope="common", keyword="예시 공통")
        done = sm.apply_fields(base, {"priority": True, "excluded_keywords": ("제외 하나",), "priority_keywords": ("우선 하나",), "reason": "예시 이유", "allowed_channels": ("naver_a", "naver_b")})
        self.assertEqual((done.priority, done.excluded_keywords, done.priority_keywords, done.reason, done.allowed_channels), (True, ("제외 하나",), ("우선 하나",), "예시 이유", ("naver_a", "naver_b")))
        self.assertEqual(done.state, "proposed", "고쳐도 상태는 그대로")
        with self.assertRaises(sm.SeedProblems) as caught:
            sm.apply_fields(base, {"priority": "yes", "reason": "가" * (sd.MAX_REASON + 1), "excluded_keywords": ("같음", "같음"), "allowed_channels": ("naver_z",)})
        self.assertEqual(set(caught.exception.problems), {"priority", "reason", "allowed_channels", "excluded_keywords"}, "틀린 칸을 한꺼번에 모두 알린다")
        for bad in ({"state": "active"}, {"keyword": "다른 낱말"}, {"seed_id": "x"}, {"scope": "naver_b"}, {"seed_type": "priority"}, {"prepare_from": "01-01"}, {}):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    sm.apply_fields(base, bad)

    def test_keywords_that_are_fine_alone_but_clash_together_flag_both_fields(self):
        base = seed()
        with self.assertRaises(sm.SeedProblems) as caught:
            sm.apply_fields(base, {"priority_keywords": ("겹침",), "excluded_keywords": ("겹침",)})
        self.assertEqual(set(caught.exception.problems), {"priority_keywords", "excluded_keywords"})
        self.assertEqual(caught.exception.code, "CONTENT_INVALID")

    def test_channel_only_seeds_cannot_be_widened_by_editing_the_allowed_channels(self):
        with self.assertRaises(sm.SeedProblems) as caught:
            sm.apply_fields(seed(scope="naver_a"), {"allowed_channels": ("naver_a", "naver_b")})
        self.assertEqual(set(caught.exception.problems), {"allowed_channels"})

    def test_a_new_seed_is_always_proposed_and_its_number_is_chosen_here(self):
        made = sm.new_seed([seed("M001")], create_fields(seed_type="priority", scope="common", allowed_channels=("naver_a", "github_pages"), sponsor_tag=None), DAY)
        self.assertEqual((made.state, made.seed_id, made.registered_on, made.active_since, made.last_selected_on), ("proposed", "M002", DAY, None, None))
        self.assertEqual((made.priority, made.allowed_channels, made.needs_region, made.brand_case), (True, ("github_pages", "naver_a"), False, False))
        general = sm.new_seed([], create_fields(), DAY)
        self.assertEqual((general.priority, general.allowed_channels), (False, ("naver_a",)), "우선 표시는 중요도가 우선일 때만 켠다 · 채널 전용 씨앗은 그 채널만 허용")

    def test_a_region_placeholder_in_the_word_turns_the_region_flag_on_by_itself(self):
        made = sm.new_seed([], create_fields(keyword=sd.REGION_PLACEHOLDER + " 예시 행사"), DAY)
        self.assertTrue(made.needs_region)

    def test_new_seed_refuses_seasonal_missing_target_duplicates_and_wrong_calls(self):
        for fields, expected in ((create_fields(seed_type="seasonal"), {"seed_type"}), (create_fields(target_type=None), {"target_type"}), (create_fields(keyword=""), {"keyword"}),
                                 (create_fields(seed_type="sponsorable"), {"sponsor_tag"}), (create_fields(scope="naver_z"), {"scope"}), (create_fields(major="가" * 99), {"major"})):
            with self.subTest(fields=fields):
                with self.assertRaises(sm.SeedProblems) as caught:
                    sm.new_seed([], fields, DAY)
                self.assertEqual(set(caught.exception.problems), expected)
        with self.assertRaises(sm.SeedProblems) as caught:
            sm.new_seed([seed("ex-1", keyword="예시 새 낱말")], create_fields(), DAY)
        self.assertEqual(caught.exception.problems, {"keyword": "duplicate"})
        same_word_other_scope = sm.new_seed([seed("ex-1", keyword="예시 새 낱말", scope="naver_b")], create_fields(), DAY)
        self.assertEqual(same_word_other_scope.scope, "naver_a", "다른 소속의 같은 낱말은 괜찮다")
        for fields in ({"keyword": "x"}, {**create_fields(), "state": "active"}, {**create_fields(), "seed_id": "x"}):
            with self.assertRaises(ValueError):
                sm.new_seed([], fields, DAY)

    def test_the_guard_lets_only_the_named_seeds_change_state_and_only_by_the_allowed_transitions(self):
        before = tuple(three())
        rule = sm._Rules(frozenset(("ex-1",)), frozenset(), frozenset(), False)
        approved = dataclasses.replace(before[0], state="active", active_since=DAY)
        self.assertEqual(sm._guard(before, (approved, *before[1:]), rule), ("ex-1",))
        sneaky = dataclasses.replace(before[1], state="active", active_since=DAY)
        with self.assertRaises(AppError) as caught:
            sm._guard(before, (approved, sneaky, before[2]), rule)
        self.assertEqual(caught.exception.code, "CONTENT_INVALID", "부르지 않은 씨앗의 상태가 바뀌려 하면 막는다")
        rested = dataclasses.replace(approved, state="inactive")
        self.assertEqual(sm._guard((approved, *before[1:]), (rested, *before[1:]), rule), ("ex-1",), "사용 중 → 쉬는 중 은 허용")
        with self.assertRaises(AppError):
            sm._guard((approved, *before[1:]), (dataclasses.replace(approved, state="proposed", active_since=None), *before[1:]), rule)

    def test_the_guard_refuses_new_seeds_that_are_not_proposed_deleted_seeds_reordered_seeds_and_unlisted_fields(self):
        before = tuple(three())
        add = sm._Rules(frozenset(), frozenset(), frozenset(), True)
        self.assertEqual(sm._guard(before, (*before, seed("ex-4")), add), ("ex-4",))
        smuggled_start = dataclasses.replace(seed("ex-4"))
        object.__setattr__(smuggled_start, "active_since", DAY)
        smuggled_pick = dataclasses.replace(seed("ex-4"))
        object.__setattr__(smuggled_pick, "last_selected_on", DAY)
        for bad in (active("ex-4"), seed("ex-4", state="inactive", active_since="2026-10-01"), smuggled_start, smuggled_pick):
            with self.subTest(state=bad.state, since=bad.active_since, picked=bad.last_selected_on), self.assertRaises(AppError):
                sm._guard(before, (*before, bad), add)
        with self.assertRaises(AppError):
            sm._guard(before, (*before, seed("ex-4")), sm._Rules(frozenset(), frozenset(), frozenset(), False))
        with self.assertRaises(AppError):
            sm._guard(before, before[:2], add)
        with self.assertRaises(AppError):
            sm._guard(before, (before[1], before[0], before[2]), add)
        field_rule = sm._Rules(frozenset(), frozenset(("ex-1",)), frozenset(sm.EDITABLE), False)
        self.assertEqual(sm._guard(before, (dataclasses.replace(before[0], priority=True), *before[1:]), field_rule), ("ex-1",))
        for bad in (dataclasses.replace(before[0], keyword="다른 낱말"), dataclasses.replace(before[0], state="active", active_since=DAY), dataclasses.replace(before[0], major="다른 대분류")):
            with self.assertRaises(AppError):
                sm._guard(before, (bad, *before[1:]), field_rule)


# ---- 읽기 ----------------------------------------------------------------------------------------------------------------------------
class ReadTest(Base):
    def test_a_missing_file_reads_as_an_empty_list_and_nothing_is_created(self):
        before = self.listing()
        snap = self.snap()
        self.assertEqual((snap.seeds, snap.version, snap.state, snap.today, snap.idle), ((), sm.VERSION_MISSING, tf.STATE_MISSING, DAY, ()))
        self.assertEqual(self.listing(), before, "읽기는 파일도 폴더도 만들지 않는다")
        self.assertFalse(self.paths.folder.exists())

    def test_a_zero_byte_file_is_not_there_yet_and_reading_does_not_touch_it(self):
        self.paths.folder.mkdir(parents=True)
        self.paths.seeds.write_bytes(b"")
        snap = self.snap()
        self.assertEqual((snap.state, snap.seeds), (tf.STATE_MISSING, ()))
        self.assertNotEqual(snap.version, sm.VERSION_MISSING)
        self.assertEqual(self.paths.seeds.read_bytes(), b"")

    def test_a_good_file_reads_back_with_a_version_that_follows_the_content(self):
        self.put(three())
        first = self.snap()
        self.assertEqual((first.state, len(first.seeds)), (tf.STATE_OK, 3))
        self.assertEqual(self.snap().version, first.version)
        self.state("ex-1", "active")
        self.assertNotEqual(self.snap().version, first.version)

    def test_an_unreadable_or_wrong_file_stops_with_an_error_and_is_never_fixed_or_overwritten(self):
        self.paths.folder.mkdir(parents=True)
        good = sd.seeds_to_dict(three())
        bad_value = json.loads(json.dumps(good))
        bad_value["seeds"][0]["state"] = "approved"
        twice = json.loads(json.dumps(good))
        twice["seeds"].append(dict(twice["seeds"][0]))
        cases = ((b"{broken", "TOPIC_FILE_INVALID"), (b"\xff\xfe\x00", "TOPIC_FILE_INVALID"), (b"[1]", "CONTENT_INVALID"), (json.dumps({**good, "schema": 9}).encode(), "CONTENT_INVALID"),
                 (json.dumps(bad_value).encode(), "CONTENT_INVALID"), (json.dumps(twice).encode(), "CONTENT_INVALID"))
        for raw, code in cases:
            with self.subTest(raw=raw[:20]):
                self.paths.seeds.write_bytes(raw)
                self.assertEqual(code_of(sm.read_snapshot, self.ctx), code)
                self.assertEqual(code_of(sm.set_state, self.ctx, "ex-1", "active", expected_version="x" * 64), code, "틀린 파일 위에는 쓰지 않는다")
                self.assertEqual(code_of(sm.create_seed, self.ctx, create_fields(), expected_version="x" * 64), code)
                self.assertEqual(self.paths.seeds.read_bytes(), raw)
        self.paths.seeds.unlink()
        self.paths.seeds.mkdir()
        self.assertEqual(code_of(sm.read_snapshot, self.ctx), "TOPIC_FILE_INVALID", "파일 자리에 폴더가 있다")

    def test_a_version_one_file_reads_and_fills_the_new_fields_with_defaults(self):
        self.put(three(), schema=1)
        snap = self.snap()
        self.assertEqual(snap.state, tf.STATE_OK)
        self.assertEqual([item.target_type for item in snap.seeds], [None, None, None])

    def test_the_180_day_proposals_are_only_shown_and_nothing_is_changed_by_reading(self):
        old = active("ex-old", registered_on="2026-04-01", active_since=None)
        fresh = active("ex-new", registered_on="2026-10-20", active_since=None)
        season = active("ex-season", registered_on="2026-04-01", active_since=None, seed_type="seasonal")
        self.put([old, fresh, season, seed("ex-p", registered_on="2026-04-01")])
        before = self.tree()
        snap = self.snap()
        self.assertEqual([item.seed_id for item in snap.idle], ["ex-old"], "계절형·승인 전·최근 씨앗은 제안에 없다")
        self.assertEqual(snap.idle[0].idle_days, (sd.date.fromisoformat(DAY) - sd.date.fromisoformat("2026-04-01")).days)
        self.assertEqual(self.tree(), before)
        self.assertEqual(self.by_id()["ex-old"].state, "active", "제안만 하고 자동으로 쉬게 하지 않는다")

    def test_the_generation_flags_come_from_the_channel_profiles_and_an_unreadable_file_means_unknown(self):
        self.assertEqual(dict(self.snap().generation), {"github_pages": False, "blogger_en": False, "blogger_ko": False, "naver_a": True, "naver_b": True})
        self.paths.folder.mkdir(parents=True)
        self.paths.profiles.write_bytes(b"{broken")
        snap = self.snap()
        self.assertEqual(dict(snap.generation), {channel: None for channel in channels.CHANNELS}, "읽지 못하면 켜져 있다고 짐작하지 않는다")
        self.assertEqual(self.paths.profiles.read_bytes(), b"{broken", "채널 프로필은 읽기만 한다")


# ---- 상태 바꾸기 ----------------------------------------------------------------------------------------------------------------------
class StateChangeTest(Base):
    def test_approving_a_proposed_seed_makes_it_active_from_today_and_touches_nothing_else(self):
        self.put(three())
        before = self.by_id()
        saved = self.state("ex-1", "active")
        after = self.by_id(saved.snapshot)
        self.assertEqual((saved.kind, saved.changed, saved.backed_up), ("saved", ("ex-1",), True))
        self.assertEqual((after["ex-1"].state, after["ex-1"].active_since), ("active", DAY))
        self.assertEqual((after["ex-2"], after["ex-3"]), (before["ex-2"], before["ex-3"]), "다른 씨앗은 그대로")
        self.assertEqual(dataclasses.replace(after["ex-1"], state="proposed", active_since=None), before["ex-1"], "상태와 사용 시작일 말고는 그대로")
        self.assertEqual(json.loads(self.bytes_of())["schema"], 2)

    def test_every_allowed_transition_works_and_every_other_one_is_refused_without_writing(self):
        for start, end in (("proposed", "active"), ("proposed", "inactive"), ("active", "inactive"), ("inactive", "active")):
            with self.subTest(start=start, end=end):
                self.put([seed("ex-1", state=start, active_since="2026-10-01" if start != "proposed" else None)])
                self.assertEqual(self.state("ex-1", end).kind, "saved")
                self.assertEqual(self.by_id()["ex-1"].state, end)
        for start, end in (("active", "proposed"), ("inactive", "proposed"), ("active", "active"), ("proposed", "proposed"), ("inactive", "inactive"), ("proposed", "approved")):
            with self.subTest(start=start, end=end, kind="거절"):
                self.put([seed("ex-1", state=start, active_since="2026-10-01" if start != "proposed" else None)])
                before = self.tree()
                self.assertEqual(code_of(self.state, "ex-1", end), "CONTENT_INVALID")
                self.assertEqual(self.tree(), before)
        self.assertEqual({key: tuple(value) for key, value in sd.TRANSITIONS.items()}, {"proposed": ("active", "inactive"), "active": ("inactive",), "inactive": ("active",)})

    def test_an_unknown_number_and_a_date_before_the_registration_day_are_refused(self):
        self.put(three())
        before = self.tree()
        self.assertEqual(code_of(self.state, "ex-none", "active"), "CONTENT_INVALID")
        self.assertEqual(code_of(self.state, 7, "active"), "CONTENT_INVALID")
        self.put([seed("ex-1", registered_on="2026-12-01")])
        again = self.tree()
        self.assertEqual(code_of(self.state, "ex-1", "active"), "CONTENT_INVALID", "오늘이 등록일보다 앞서면(컴퓨터 날짜 이상) 사용 시작일을 적지 않는다")
        self.assertEqual(self.tree(), again)
        self.assertNotEqual(before, again)

    def test_the_active_since_day_starts_the_180_day_clock_over_when_a_seed_is_used_again(self):
        self.put([seed("ex-1", state="inactive", registered_on="2026-01-01", active_since="2026-02-01")])
        self.state("ex-1", "active")
        item = self.by_id()["ex-1"]
        self.assertEqual(item.active_since, DAY)
        self.assertEqual(self.snap().idle, (), "다시 쓰기 시작한 날부터 센다")

    def test_a_key_shaped_seed_cannot_have_its_state_changed_and_the_error_never_shows_the_text(self):
        self.put([seed("ex-1", keyword="예시 " + KEY_SHAPED), seed("ex-2")])
        before = self.tree()
        with self.assertRaises(sm.SeedProblems) as caught:
            self.state("ex-1", "active")
        self.assertEqual(caught.exception.problems, {"keyword": "key_shape"})
        self.assertNotIn(KEY_SHAPED, repr(caught.exception.problems) + str(caught.exception) + caught.exception.detail + caught.exception.log_line())
        self.assertEqual(self.tree(), before)
        self.assertEqual(self.state("ex-2", "active").kind, "saved", "키 모양 씨앗이 있어도 다른 씨앗은 바꿀 수 있다")

    def test_a_stale_version_writes_nothing_and_says_conflict(self):
        self.put(three())
        first = self.snap().version
        self.state("ex-1", "active")
        before = self.tree()
        for call in (lambda: sm.set_state(self.ctx, "ex-2", "active", expected_version=first, today=DAY),
                     lambda: sm.set_states(self.ctx, ["ex-2", "ex-3"], "active", confirmed=True, expected_count=2, expected_version=first, today=DAY),
                     lambda: sm.edit_seed(self.ctx, "ex-2", {"priority": True}, expected_version=first),
                     lambda: sm.create_seed(self.ctx, create_fields(), expected_version=first, today=DAY),
                     lambda: sm.set_state(self.ctx, "ex-2", "active", expected_version="not-a-version", today=DAY)):
            self.assertEqual(code_of(call), "STORE_CONFLICT")
        self.assertEqual(self.tree(), before)

    def test_a_file_changed_by_hand_after_the_screen_read_it_is_not_overwritten(self):
        self.put(three())
        seen = self.snap().version
        self.put([*three(), seed("ex-4")])
        hand = self.bytes_of()
        self.assertEqual(code_of(sm.set_state, self.ctx, "ex-1", "active", expected_version=seen, today=DAY), "STORE_CONFLICT")
        self.assertEqual(self.bytes_of(), hand)


# ---- 한꺼번에 바꾸기(Seed 일괄 변경) ------------------------------------------------------------------------------------------------------
class BulkTest(Base):
    def bulk(self, ids, state, *, count=None, confirmed=True, version=None):
        return sm.set_states(self.ctx, ids, state, confirmed=confirmed, expected_count=len(ids) if count is None else count,
                             expected_version=self.snap().version if version is None else version, today=DAY)

    def test_all_the_chosen_seeds_change_in_one_write_and_the_others_stay(self):
        self.put([seed(f"ex-{n}") for n in range(1, 7)])
        before = self.by_id()
        writes = []
        real = sm.write_json
        with mock.patch.object(sm, "write_json", lambda path, data: (writes.append(Path(path).name), real(path, data))[1]):
            saved = self.bulk(["ex-1", "ex-3", "ex-5"], "active")
        self.assertEqual(writes.count("seeds.json"), 1, "한 번의 쓰기")
        after = self.by_id(saved.snapshot)
        self.assertEqual(sorted(saved.changed), ["ex-1", "ex-3", "ex-5"])
        self.assertEqual([after[key].state for key in ("ex-1", "ex-3", "ex-5")], ["active"] * 3)
        self.assertEqual([after[key].state for key in ("ex-2", "ex-4", "ex-6")], ["proposed"] * 3)
        self.assertEqual([after[key].active_since for key in ("ex-1", "ex-3", "ex-5")], [DAY] * 3)
        for key in ("ex-2", "ex-4", "ex-6"):
            self.assertEqual(after[key], before[key])

    def test_it_is_all_or_nothing_one_bad_seed_stops_every_change(self):
        self.put([seed("ex-1"), seed("ex-2"), active("ex-3"), seed("ex-4")])
        before = self.tree()
        self.assertEqual(code_of(self.bulk, ["ex-1", "ex-2", "ex-3", "ex-4"], "active"), "CONTENT_INVALID", "이미 사용 중인 씨앗이 끼어 있다")
        self.assertEqual(code_of(self.bulk, ["ex-1", "ex-none"], "active"), "CONTENT_INVALID")
        self.assertEqual(self.tree(), before, "하나도 안 바뀌었다(앞의 씨앗도 그대로)")
        self.assertEqual(self.leftovers(), [])

    def test_the_mixed_origin_states_move_to_the_target_when_every_move_is_allowed(self):
        self.put([seed("ex-1"), seed("ex-2", state="inactive", active_since="2026-10-01"), seed("ex-3")])
        self.assertEqual(self.bulk(["ex-1", "ex-2"], "active").kind, "saved")
        after = self.by_id()
        self.assertEqual([after[key].state for key in ("ex-1", "ex-2", "ex-3")], ["active", "active", "proposed"])
        self.put([seed("ex-1"), active("ex-2"), seed("ex-3", state="inactive", active_since="2026-10-01")])
        self.assertEqual(code_of(self.bulk, ["ex-1", "ex-2", "ex-3"], "inactive"), "CONTENT_INVALID", "쉬는 중 → 쉬는 중 은 없는 전환")

    def test_the_confirmation_needs_the_real_true_and_the_count_that_the_dialog_showed_and_nothing_is_read_without_it(self):
        self.put(three())
        before = self.tree()
        for value in (False, None, 1, "yes", "true", [True]):
            with self.subTest(confirmed=value), mock.patch.object(sm, "_read", side_effect=AssertionError("읽으면 안 된다")):
                self.assertEqual(code_of(self.bulk, ["ex-1"], "active", confirmed=value, version="x"), "CONFIRMATION_REQUIRED")
        with self.assertRaises(TypeError):
            sm.set_states(self.ctx, ["ex-1"], "active", expected_count=1, expected_version="x")
        for count in (0, 2, 99, None, True, "1"):
            with self.subTest(count=count):
                self.assertEqual(code_of(sm.set_states, self.ctx, ["ex-1"], "active", confirmed=True, expected_count=count, expected_version=self.snap().version, today=DAY), "CONFIRMATION_REQUIRED",
                                 "확인한 개수와 다르면 쓰지 않는다")
        self.assertEqual(self.tree(), before)

    def test_wrong_number_lists_are_a_code_mistake_and_write_nothing(self):
        self.put(three())
        before = self.tree()
        for ids in ([], ["ex-1", "ex-1"], [1, 2], "ex-1ex-2"[:0]):
            with self.subTest(ids=ids), self.assertRaises(ValueError):
                self.bulk(ids, "active", count=len(ids))
        self.assertEqual(self.tree(), before)

    def test_nothing_is_ever_deleted_by_a_change_of_state(self):
        self.put([seed(f"ex-{n}") for n in range(1, 5)])
        self.bulk(["ex-1", "ex-2", "ex-3", "ex-4"], "inactive")
        self.assertEqual([item.seed_id for item in self.snap().seeds], ["ex-1", "ex-2", "ex-3", "ex-4"])
        self.assertEqual({item.state for item in self.snap().seeds}, {"inactive"})


# ---- 고치기 ---------------------------------------------------------------------------------------------------------------------------
class EditTest(Base):
    def edit(self, seed_id="ex-1", fields=None, version=None):
        return sm.edit_seed(self.ctx, seed_id, {"priority": True} if fields is None else fields, expected_version=self.snap().version if version is None else version)

    def test_an_edit_changes_only_the_edited_fields_of_that_seed_and_never_the_state(self):
        self.put([active("ex-1"), seed("ex-2")])
        before = self.by_id()
        saved = self.edit("ex-1", {"priority": True, "excluded_keywords": ("제외 하나",), "priority_keywords": ("우선 하나", "우선 둘"), "reason": "예시 이유"})
        after = self.by_id(saved.snapshot)
        self.assertEqual((saved.kind, saved.changed), ("saved", ("ex-1",)))
        self.assertEqual((after["ex-1"].priority, after["ex-1"].excluded_keywords, after["ex-1"].priority_keywords, after["ex-1"].reason), (True, ("제외 하나",), ("우선 하나", "우선 둘"), "예시 이유"))
        self.assertEqual((after["ex-1"].state, after["ex-1"].active_since, after["ex-1"].keyword, after["ex-1"].registered_on), (before["ex-1"].state, before["ex-1"].active_since, before["ex-1"].keyword, before["ex-1"].registered_on))
        self.assertEqual(after["ex-2"], before["ex-2"])

    def test_a_seasonal_seed_keeps_its_schedule_while_other_fields_are_edited(self):
        season = seed("ex-1", seed_type="seasonal", prepare_from="12-05", publish_from="12-20", publish_until="01-20", peak_period=("12-28", "01-10"), recurrence="yearly", scope="common", keyword="예시 계절")
        self.put([season])
        self.edit("ex-1", {"priority": True, "reason": "예시 계절 이유"})
        done = self.by_id()["ex-1"]
        self.assertEqual((done.prepare_from, done.publish_from, done.publish_until, done.peak_period, done.recurrence), ("12-05", "12-20", "01-20", ("12-28", "01-10"), "yearly"))
        self.assertTrue(done.priority)

    def test_a_save_without_any_change_writes_nothing_and_creates_no_lock(self):
        self.put(three())
        before, listing = self.tree(), self.listing()
        again = self.edit("ex-1", {"priority": False, "reason": ""})
        self.assertEqual((again.kind, again.changed, again.backed_up), ("unchanged", (), False))
        self.assertEqual((self.tree(), self.listing()), (before, listing))

    def test_wrong_values_are_named_per_field_and_nothing_is_written(self):
        self.put(three())
        before, listing = self.tree(), self.listing()
        cases = {"priority": "yes", "reason": "가" * (sd.MAX_REASON + 1), "excluded_keywords": ["같음", "같음"], "priority_keywords": ["가" * (sd.MAX_EXCLUDED_WORD + 1)], "allowed_channels": ["naver_a", "naver_z"]}
        for name, value in cases.items():
            with self.subTest(field=name), self.assertRaises(sm.SeedProblems) as caught:
                self.edit("ex-3", {name: value})
            self.assertEqual(caught.exception.problems, {name: "invalid"})
            self.assertEqual(caught.exception.code, "CONTENT_INVALID")
        self.assertEqual((self.tree(), self.listing()), (before, listing))

    def test_key_shaped_text_is_refused_before_anything_is_written_and_names_the_field(self):
        self.put(three())
        before = self.tree()
        for name, value in (("reason", "이유 " + KEY_SHAPED), ("excluded_keywords", ("제외 " + KEY_SHAPED,)), ("priority_keywords", ("우선 " + KEY_SHAPED,))):
            with self.subTest(field=name), self.assertRaises(sm.SeedProblems) as caught:
                self.edit("ex-1", {name: value})
            self.assertEqual(caught.exception.problems, {name: "key_shape"})
            self.assertNotIn(KEY_SHAPED, repr(caught.exception.problems) + str(caught.exception) + caught.exception.detail + caught.exception.log_line())
        self.assertEqual(self.tree(), before)

    def test_fields_the_screen_may_not_edit_are_a_code_mistake_and_an_unknown_number_is_refused(self):
        self.put(three())
        for fields in ({"state": "active"}, {"keyword": "다른 낱말"}, {"seed_id": "x"}, {}):
            with self.assertRaises(ValueError):
                self.edit("ex-1", fields)
        self.assertEqual(code_of(self.edit, "ex-none"), "CONTENT_INVALID")


# ---- 새로 등록 ------------------------------------------------------------------------------------------------------------------------
class CreateTest(Base):
    def create(self, **changes):
        return sm.create_seed(self.ctx, create_fields(**changes), expected_version=self.snap().version, today=DAY)

    def test_the_first_registration_creates_the_folder_and_a_proposed_seed_with_the_first_number(self):
        saved = self.create()
        self.assertEqual((saved.kind, saved.changed, saved.backed_up), ("saved", ("M001",), False))
        item = self.by_id()["M001"]
        self.assertEqual((item.state, item.active_since, item.last_selected_on, item.registered_on, item.keyword), ("proposed", None, None, DAY, "예시 새 낱말"))
        self.assertEqual(json.loads(self.bytes_of())["schema"], 2)

    def test_there_is_no_way_to_register_a_seed_as_active_or_with_a_chosen_number(self):
        for extra in ({"state": "active"}, {"seed_id": "mine"}, {"active_since": DAY}, {"registered_on": DAY}):
            with self.assertRaises(ValueError):
                sm.create_seed(self.ctx, {**create_fields(), **extra}, expected_version=self.snap().version, today=DAY)
        self.assertFalse(self.paths.seeds.exists())

    def test_the_next_registrations_get_the_next_numbers_are_added_at_the_end_and_keep_a_copy(self):
        self.put(three())
        self.create(keyword="예시 둘째")
        saved = self.create(keyword="예시 셋째")
        ids = [item.seed_id for item in saved.snapshot.seeds]
        self.assertEqual(ids, ["ex-1", "ex-2", "ex-3", "M001", "M002"])
        self.assertTrue(saved.backed_up)
        bak = self.paths.seeds.with_name(sm.BACKUP_NAME)
        self.assertEqual([item["seed_id"] for item in json.loads(bak.read_bytes())["seeds"]], ["ex-1", "ex-2", "ex-3", "M001"], "사본은 직전 내용")

    def test_the_same_word_in_the_same_scope_is_refused_even_with_other_spacing_and_the_form_names_the_field(self):
        self.create()
        before = self.tree()
        for word in ("예시 새 낱말", "예시새낱말", "예시-새-낱말", "예시 새 낱말 "):
            with self.subTest(word=word), self.assertRaises(sm.SeedProblems) as caught:
                self.create(keyword=word)
            self.assertEqual(caught.exception.problems, {"keyword": "duplicate"})
        self.assertEqual(self.tree(), before)
        self.assertEqual(self.create(scope="naver_b").kind, "saved", "다른 소속의 같은 낱말은 괜찮다")

    def test_an_importance_that_needs_a_tag_and_a_seasonal_importance_are_handled(self):
        with self.assertRaises(sm.SeedProblems) as caught:
            self.create(seed_type="sponsorable")
        self.assertEqual(set(caught.exception.problems), {"sponsor_tag"})
        done = self.create(seed_type="sponsorable", sponsor_tag="pc_parts", keyword="예시 협찬 낱말")
        self.assertEqual(self.by_id(done.snapshot)["M001"].sponsor_tag, "pc_parts")
        with self.assertRaises(sm.SeedProblems) as caught:
            self.create(seed_type="seasonal", keyword="예시 계절 낱말")
        self.assertEqual(set(caught.exception.problems), {"seed_type"})

    def test_a_common_seed_can_name_its_channels_and_a_region_word_asks_for_the_region(self):
        saved = self.create(scope="common", allowed_channels=("naver_b", "naver_a"), keyword=sd.REGION_PLACEHOLDER + " 예시 장소", target_type="place")
        item = self.by_id(saved.snapshot)["M001"]
        self.assertEqual((item.allowed_channels, item.needs_region, item.scope), (("naver_a", "naver_b"), True, "common"))

    def test_key_shaped_text_in_any_text_field_is_refused_before_anything_is_written(self):
        before = self.listing()
        for name, value in (("keyword", "예시 " + KEY_SHAPED), ("major", KEY_SHAPED), ("minor", KEY_SHAPED), ("reason", KEY_SHAPED), ("excluded_keywords", (KEY_SHAPED,)), ("priority_keywords", (KEY_SHAPED,))):
            with self.subTest(field=name), self.assertRaises(sm.SeedProblems) as caught:
                self.create(**{name: value})
            self.assertEqual(caught.exception.problems, {name: "key_shape"})
        self.assertEqual(self.listing(), before, "아무것도 만들지 않았다")

    def test_the_limit_of_seeds_is_kept(self):
        self.put([seed(f"ex-{n:04d}", keyword=f"예시 낱말 {n}") for n in range(sd.MAX_SEEDS)])
        self.assertEqual(code_of(self.create), "CONTENT_INVALID")


# ---- 제안 파일 불러오기 --------------------------------------------------------------------------------------------------------------------
class ImportTest(Base):
    def source(self, *entries, **top):
        path = self.tmp / "proposal.json"
        path.write_text(json.dumps(proposal_file(*entries, **top), ensure_ascii=False), encoding="utf-8")
        return path

    def entries(self, count=3):
        return [proposal(id=f"EX{n:03d}", keyword=f"예시 물건 {n}") for n in range(1, count + 1)]

    def test_the_preview_only_reads_and_creates_not_even_the_data_folder(self):
        path = self.source(*self.entries())
        before = self.listing()
        preview = sm.preview_import(self.ctx, path, today=DAY)
        self.assertEqual((len(preview.result.new), preview.result.applied, preview.result.blocked, preview.version, preview.today), (3, False, False, sm.VERSION_MISSING, DAY))
        self.assertEqual(self.listing(), before)
        self.assertFalse(self.paths.seeds.exists())

    def test_applying_adds_every_seed_as_proposed_in_one_write_and_keeps_the_existing_ones(self):
        self.put([seed("ex-1")])
        preview = sm.preview_import(self.ctx, self.source(*self.entries(4), default_status="active"), today=DAY)
        saved = sm.apply_import(self.ctx, preview.result.new, expected_version=preview.version)
        self.assertEqual((saved.kind, len(saved.changed), saved.backed_up), ("saved", 4, True))
        states = {item.seed_id: item.state for item in saved.snapshot.seeds}
        self.assertEqual(states, {"ex-1": "proposed", "EX001": "proposed", "EX002": "proposed", "EX003": "proposed", "EX004": "proposed"}, "파일이 다른 상태를 적었어도 모두 승인 전")
        again = sm.preview_import(self.ctx, self.source(*self.entries(4)), today=DAY)
        self.assertEqual((len(again.result.new), len(again.result.skipped)), (0, 4), "다시 불러와도 이미 있는 씨앗은 건너뛴다")

    def test_a_seed_that_is_not_proposed_is_never_accepted_by_the_apply_step(self):
        self.put([seed("ex-1")])
        before = self.tree()
        version = self.snap().version
        for bad in (active("EX900"), seed("EX901", state="inactive", active_since="2026-10-01")):
            with self.subTest(state=bad.state):
                self.assertEqual(code_of(sm.apply_import, self.ctx, (bad,), expected_version=version), "CONTENT_INVALID")
        with self.assertRaises(ValueError):
            sm.apply_import(self.ctx, ("not a seed",), expected_version=version)
        self.assertEqual(self.tree(), before)

    def test_a_seed_with_a_selection_or_start_day_cannot_be_smuggled_in_as_proposed_either(self):
        self.put([seed("ex-1")])
        smuggled = dataclasses.replace(seed("EX905"))
        object.__setattr__(smuggled, "active_since", DAY)
        before = self.tree()
        self.assertEqual(code_of(sm.apply_import, self.ctx, (smuggled,), expected_version=self.snap().version), "CONTENT_INVALID")
        self.assertEqual(self.tree(), before)

    def test_a_file_changed_between_the_preview_and_the_apply_is_not_written(self):
        self.put([seed("ex-1")])
        preview = sm.preview_import(self.ctx, self.source(*self.entries(2)), today=DAY)
        self.state("ex-1", "active")
        before = self.tree()
        self.assertEqual(code_of(sm.apply_import, self.ctx, preview.result.new, expected_version=preview.version), "STORE_CONFLICT")
        self.assertEqual(self.tree(), before)

    def test_a_number_or_word_that_appeared_after_the_preview_stops_the_apply(self):
        """미리 본 뒤에 같은 번호나 같은 소속의 같은 낱말이 생기면 아무것도 쓰지 않고, **그 이유를 쉬운 말로** 알린다(뒤의 일반 검사가 같은 코드로 막더라도 이 이유 문장은 이 검사에서만 나온다)."""
        def refusal(version):
            try:
                sm.apply_import(self.ctx, preview.result.new, expected_version=version)
            except AppError as error:
                return error
            self.fail("거절되지 않았다")

        preview = sm.preview_import(self.ctx, self.source(*self.entries(2)), today=DAY)
        for existing, why in ((seed("EX001", keyword="예시 다른 낱말"), "같은 번호"), (seed("ex-7", keyword="예시 물건 1"), "같은 소속의 같은 낱말")):
            self.put([existing])
            before = self.tree()
            error = refusal(self.snap().version)
            self.assertEqual(error.code, "CONTENT_INVALID", why)
            self.assertIn("미리 본 뒤에 같은 번호나 같은 낱말이 생겼다", error.detail, why)
            self.assertEqual(self.tree(), before, why + " — 아무것도 쓰지 않았다")

    def test_rejected_seeds_are_shown_in_the_preview_and_key_shaped_text_is_not_repeated(self):
        bad = proposal(id="EX777", keyword="예시 틀린 것", target_type="gadget")
        leaky = proposal(id="EX778", keyword="예시 " + KEY_SHAPED)
        preview = sm.preview_import(self.ctx, self.source(*self.entries(2), bad, leaky), today=DAY)
        self.assertEqual((preview.result.blocked, sorted(name for name, _why in preview.result.rejected)), (True, ["EX777", "EX778"]))
        self.assertNotIn(KEY_SHAPED, json.dumps(preview.result.to_dict(), ensure_ascii=False))

    def test_a_broken_current_file_stops_the_preview_and_a_missing_proposal_file_is_a_plain_error(self):
        self.paths.folder.mkdir(parents=True)
        self.paths.seeds.write_bytes(b"{broken")
        self.assertEqual(code_of(sm.preview_import, self.ctx, self.source(*self.entries()), today=DAY), "TOPIC_FILE_INVALID")
        self.paths.seeds.unlink()
        self.assertEqual(code_of(sm.preview_import, self.ctx, self.tmp / "none.json", today=DAY), "CONTENT_INVALID")
        self.assertEqual(code_of(sm.preview_import, self.ctx, self.tmp, today=DAY), "CONTENT_INVALID", "폴더를 고르면")


# ---- 승인 전 씨앗은 후보 생성에 새지 않는다 ----------------------------------------------------------------------------------------------
class ProposedSeedsNeverFeedCandidatesTest(unittest.TestCase):
    """이 묶음의 가장 큰 위험 — 승인하기 전의 씨앗에서 후보가 만들어지는 일. 실제 후보 계획(`plan_candidates`)으로 본다."""

    @staticmethod
    def seed_ids(world):
        found = world.plan(channel="naver_a", target=20)
        return {candidate.seed_id for plan in found.plans for candidate in plan.candidates if candidate.source_type == "seed"}

    def test_registered_and_imported_seeds_stay_out_of_the_plan_until_approved_and_leave_again_when_rested(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = World(tmp, with_world=False)
            ctx = world.ctx
            version = sm.read_snapshot(ctx).version
            first = sm.create_seed(ctx, create_fields(keyword="예시 제습기", scope="naver_a"), expected_version=version, today=PLAN_DAY)
            source = Path(tmp) / "proposal.json"
            source.write_text(json.dumps(proposal_file(proposal(id="EX001", keyword="예시 가습기", scope="naver_a", allowed_channels=["naver_a"]), proposal(id="EX002", keyword="예시 청소기", scope="common", allowed_channels=["naver_a", "naver_b"])),
                                         ensure_ascii=False), encoding="utf-8")
            preview = sm.preview_import(ctx, source, today=PLAN_DAY)
            sm.apply_import(ctx, preview.result.new, expected_version=preview.version)
            snap = sm.read_snapshot(ctx, today=PLAN_DAY)
            self.assertEqual({item.state for item in snap.seeds}, {"proposed"})
            self.assertEqual(sd.usable_seeds(snap.seeds, "naver_a"), (), "승인 전 씨앗은 쓸 수 있는 씨앗이 아니다")
            self.assertEqual(self.seed_ids(world), set(), "승인 전 씨앗에서 후보가 하나도 안 나온다")
            sm.set_state(ctx, "M001", "active", expected_version=snap.version, today=PLAN_DAY)
            self.assertEqual(self.seed_ids(world), {"M001"}, "승인한 씨앗에서만 후보가 나온다(나머지 승인 전 씨앗은 그대로 빠져 있다)")
            sm.set_state(ctx, "M001", "inactive", expected_version=sm.read_snapshot(ctx).version, today=PLAN_DAY)
            self.assertEqual(self.seed_ids(world), set(), "다시 쉬게 하면 후보 생성에서 빠진다")
            self.assertEqual(first.changed, ("M001",))

    def test_a_bulk_approval_feeds_only_the_approved_seeds_and_a_failed_one_changes_nothing_for_the_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = World(tmp, with_world=False)
            ctx = world.ctx
            for word in ("예시 하나", "예시 둘", "예시 셋"):
                sm.create_seed(ctx, create_fields(keyword=word), expected_version=sm.read_snapshot(ctx).version, today=PLAN_DAY)
            snap = sm.read_snapshot(ctx, today=PLAN_DAY)
            self.assertEqual(code_of(sm.set_states, ctx, ["M001", "M002", "M999"], "active", confirmed=True, expected_count=3, expected_version=snap.version, today=PLAN_DAY), "CONTENT_INVALID")
            self.assertEqual(self.seed_ids(world), set())
            sm.set_states(ctx, ["M001", "M003"], "active", confirmed=True, expected_count=2, expected_version=snap.version, today=PLAN_DAY)
            self.assertEqual(self.seed_ids(world), {"M001", "M003"})

    def test_a_seed_for_a_channel_that_generation_is_off_for_stays_unused_even_when_approved(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = World(tmp, with_world=False)
            ctx = world.ctx
            sm.create_seed(ctx, create_fields(keyword="예시 깃허브 낱말", scope="github_pages", target_type="policy"), expected_version=sm.read_snapshot(ctx).version, today=PLAN_DAY)
            sm.set_state(ctx, "M001", "active", expected_version=sm.read_snapshot(ctx).version, today=PLAN_DAY)
            profiles = tf.load_profiles(world.paths).value
            self.assertEqual(sd.usable_seeds(sm.read_snapshot(ctx).seeds, next(p for p in profiles if p.key == "github_pages")), (), "후보 생성이 꺼진 채널은 승인해도 쓰지 않는다")
            self.assertEqual(dict(sm.read_snapshot(ctx).generation)["github_pages"], False)


# ---- 백업 ------------------------------------------------------------------------------------------------------------------------------
class BackupTest(Base):
    def test_every_save_after_the_first_keeps_the_previous_valid_content_in_a_bak_file(self):
        self.put(three())
        first = self.bytes_of()
        saved = self.state("ex-1", "active")
        bak = self.paths.seeds.with_name(sm.BACKUP_NAME)
        self.assertTrue(saved.backed_up)
        self.assertEqual(json.loads(bak.read_bytes()), json.loads(first))
        self.state("ex-2", "active")
        self.assertEqual([item["state"] for item in json.loads(bak.read_bytes())["seeds"]], ["active", "proposed", "proposed"], "사본은 늘 직전 하나")

    def test_a_version_one_file_gets_an_old_shape_copy_before_it_is_upgraded(self):
        self.put(three(), schema=1)
        original = self.bytes_of()
        saved = self.state("ex-1", "active")
        old = self.paths.folder / "seeds.json.v1.bak"
        self.assertEqual(old.read_bytes(), original, "옛 모양 그대로의 사본")
        self.assertEqual(json.loads(self.bytes_of())["schema"], 2)
        self.assertTrue(saved.backed_up)

    def test_when_the_backup_cannot_be_written_the_main_file_is_not_touched(self):
        self.put(three())
        os.mkdir(self.paths.seeds.with_name(sm.BACKUP_NAME))                    # 사본 자리에 폴더 — 어느 운영체제에서나 사본을 쓸 수 없다
        before = self.tree()
        self.assertEqual(code_of(self.state, "ex-1", "active"), "FILE_WRITE_FAILED")
        self.assertEqual(self.tree(), before, "사본을 못 남기면 본 파일을 쓰지 않는다(원본 유지)")
        self.assertEqual(self.leftovers(), [])

    def test_a_zero_byte_file_has_nothing_to_back_up_and_is_replaced(self):
        self.paths.folder.mkdir(parents=True)
        self.paths.seeds.write_bytes(b"")
        saved = sm.create_seed(self.ctx, create_fields(), expected_version=self.snap().version, today=DAY)
        self.assertEqual((saved.kind, saved.backed_up), ("saved", False))
        self.assertEqual(self.snap().state, tf.STATE_OK)
        self.assertFalse(self.paths.seeds.with_name(sm.BACKUP_NAME).exists())

    def test_the_saved_file_always_reads_back_and_passes_the_topic_backup_check(self):
        from chanceblog_desktop.service import topics as topic_service
        self.put(three())
        self.state("ex-1", "active")
        sm.create_seed(self.ctx, create_fields(), expected_version=self.snap().version, today=DAY)
        self.assertEqual(len(tf.load_seeds(self.paths).value), 4)
        made = topic_service.backup_topics(self.ctx)
        self.assertIn(layout.SEEDS_FILE, made.files)


# ---- 안전망(코드 실수가 있어도 쓰지 않는다) ------------------------------------------------------------------------------------------------
class GuardIntegrationTest(Base):
    """쓰기 함수의 `mutate` 가 일부러 잘못된 일을 해도 `_commit` 이 아무것도 쓰지 않는다 — 승인하지 않은 상태 변경·승인 전이 아닌 새 씨앗·사라지는 씨앗·허락되지 않은 칸."""

    def commit(self, mutate, *, state_ids=(), field_ids=(), fields=(), add=False):
        rules = sm._Rules(frozenset(state_ids), frozenset(field_ids), frozenset(fields), add)
        return sm._commit(self.ctx, mutate, rules, self.snap().version, DAY)

    def setUp(self):
        super().setUp()
        self.put(three())
        self.before = self.tree()

    def test_a_state_change_of_a_seed_nobody_named_is_never_written(self):
        def approve_everything(seeds):
            return tuple(sd.change_state(item, "active", on=DAY) for item in seeds)

        self.assertEqual(code_of(self.commit, approve_everything, state_ids=("ex-1",)), "CONTENT_INVALID")
        self.assertEqual(self.tree(), self.before)

    def test_a_new_seed_that_is_not_proposed_is_never_written(self):
        self.assertEqual(code_of(self.commit, lambda seeds: (*seeds, active("ex-new")), add=True), "CONTENT_INVALID")
        self.assertEqual(self.tree(), self.before)

    def test_a_vanishing_seed_is_never_written(self):
        self.assertEqual(code_of(self.commit, lambda seeds: seeds[:-1], state_ids=("ex-3",)), "CONTENT_INVALID")
        self.assertEqual(self.tree(), self.before)

    def test_a_change_of_a_field_nobody_allowed_is_never_written(self):
        self.assertEqual(code_of(self.commit, lambda seeds: (dataclasses.replace(seeds[0], keyword="다른 낱말"), *seeds[1:]), field_ids=("ex-1",), fields=sm.EDITABLE), "CONTENT_INVALID")
        self.assertEqual(self.tree(), self.before)

    def test_a_seed_added_by_a_function_that_may_not_add_is_never_written(self):
        self.assertEqual(code_of(self.commit, lambda seeds: (*seeds, seed("ex-new")), state_ids=("ex-1",)), "CONTENT_INVALID")
        self.assertEqual(self.tree(), self.before)

    def test_the_guard_does_not_get_in_the_way_of_a_normal_write(self):
        saved = self.commit(lambda seeds: (sd.change_state(seeds[0], "active", on=DAY), *seeds[1:]), state_ids=("ex-1",))
        self.assertEqual((saved.kind, saved.changed), ("saved", ("ex-1",)))


# ---- 실패 주입 --------------------------------------------------------------------------------------------------------------------------
class Injector:
    """진짜 `os` 의 열기·쓰기·`fsync`·닫기·이름 바꾸기를 부르면서 원하는 곳(파일 이름 + 그 파일에 대한 n 번째 호출)에서 실패를 끼운다. `after` 면 일을 한 **뒤에** 끼운다."""

    def __init__(self, case):
        self.paths_of, self.rules, self.counts, self.log = {}, [], {}, []
        for name in REAL:
            self.install(case, name)

    def when(self, op, filename, error=None, *, nth=1, after=None):
        self.rules.append({"op": op, "filename": filename, "nth": nth, "error": error, "after": after})

    def install(self, case, name):
        real = REAL[name]

        def run(*args, **kwargs):
            target = self.target_of(name, args)
            key = (name, target)
            self.counts[key] = self.counts.get(key, 0) + 1
            self.log.append(key)
            for rule in self.rules:
                if rule["op"] == name and rule["filename"] == target and rule["nth"] == self.counts[key] and rule["after"] is None:
                    raise rule["error"]
            result = real(*args, **kwargs)
            if name == "open":
                self.paths_of[result] = Path(os.fspath(args[0])).name
            for rule in self.rules:
                if rule["op"] == name and rule["filename"] == target and rule["nth"] == self.counts[key] and rule["after"] is not None:
                    rule["after"](args)
            return result

        setattr(os, name, run)
        case.addCleanup(setattr, os, name, real)

    def target_of(self, name, args):
        if name in ("replace", "open"):
            return Path(os.fspath(args[1] if name == "replace" else args[0])).name
        return self.paths_of.get(args[0], "?")


def writing_error(number=errno.EIO):
    return OSError(number, os.strerror(number))


class FailureInjectionTest(Base):
    """쓰기 중 어디서 실패해도(백업·본 파일의 임시 파일·디스크 내려보내기·이름 바꾸기 직전·직후 검증·백업 자리·디스크 가득) 기존 값이 보존되고 다시 하면 된다."""
    MAIN = "seeds.json"

    def setUp(self):
        super().setUp()
        self.put(three())
        self.state("ex-1", "active")                                               # 이미 저장된 목록이 있는 PC(백업 규칙까지 보려고 한 번 더)
        self.before = self.tree()
        self.injector = Injector(self)

    def inject(self, op, filename, number=errno.EIO, **kwargs):
        self.injector.when(op, filename, writing_error(number), **kwargs)

    def try_save(self):
        return code_of(sm.set_states, self.ctx, ["ex-2", "ex-3"], "active", confirmed=True, expected_count=2, expected_version=self.snap().version, today=DAY)

    def assert_untouched(self, code, expected):
        self.assertEqual(code, expected)
        self.assertEqual(self.tree(), self.before, "기존 값(본 파일·사본·다른 파일)이 한 바이트도 안 바뀌었다")
        self.assertEqual(self.leftovers(), [], "임시 파일·잠금 파일이 남지 않았다")

    def assert_retry_works(self):
        for name in REAL:
            setattr(os, name, REAL[name])
        saved = sm.set_states(self.ctx, ["ex-2", "ex-3"], "active", confirmed=True, expected_count=2, expected_version=self.snap().version, today=DAY)
        self.assertEqual(saved.kind, "saved")
        self.assertEqual({item.state for item in self.snap().seeds}, {"active"})

    def test_the_backup_temp_file_fails_while_being_written(self):
        self.inject("write", sm.BACKUP_NAME + ".tmp")
        self.assert_untouched(self.try_save(), "FILE_WRITE_FAILED")
        self.assert_retry_works()

    def test_the_backup_cannot_be_put_in_place(self):
        self.inject("replace", sm.BACKUP_NAME)
        self.assert_untouched(self.try_save(), "FILE_WRITE_FAILED")
        self.assert_retry_works()

    def test_the_main_temp_file_fails_while_being_written(self):
        self.inject("write", self.MAIN + ".tmp")
        self.assert_untouched(self.try_save(), "FILE_WRITE_FAILED")
        self.assert_retry_works()

    def test_the_main_temp_file_cannot_be_flushed_to_disk(self):
        self.inject("fsync", self.MAIN + ".tmp")
        self.assert_untouched(self.try_save(), "FILE_WRITE_FAILED")
        self.assert_retry_works()

    def test_the_rename_fails_right_before_the_new_file_takes_its_place(self):
        self.inject("replace", self.MAIN)
        self.assert_untouched(self.try_save(), "FILE_WRITE_FAILED")
        self.assert_retry_works()

    def test_a_full_disk_is_reported_as_such_and_changes_nothing(self):
        self.inject("write", self.MAIN + ".tmp", errno.ENOSPC)
        self.assert_untouched(self.try_save(), "DISK_FULL")
        self.assert_retry_works()

    def test_a_full_disk_while_writing_the_backup_changes_nothing_either(self):
        self.inject("write", sm.BACKUP_NAME + ".tmp", errno.ENOSPC)
        self.assert_untouched(self.try_save(), "DISK_FULL")
        self.assert_retry_works()

    def test_a_failed_bulk_change_leaves_no_seed_changed_not_even_the_first(self):
        self.inject("replace", self.MAIN)
        self.assertEqual(self.try_save(), "FILE_WRITE_FAILED")
        self.assertEqual([item.state for item in self.snap().seeds], ["active", "proposed", "proposed"], "일부만 바뀐 상태가 없다")

    def test_a_new_file_that_reads_back_differently_is_rolled_back_to_the_previous_content(self):
        """이름을 바꾼 **직후** 파일이 다르게 읽히면(디스크·다른 프로그램) 직전 내용으로 되돌리고 실패로 알린다."""
        def corrupt(args):
            Path(os.fspath(args[1])).write_bytes(b"{garbage")

        self.injector.when("replace", self.MAIN, after=corrupt)
        self.assertEqual(self.try_save(), "FILE_WRITE_FAILED")
        self.assertEqual(json.loads(self.bytes_of()), json.loads(self.before["topic_engine/seeds.json"]), "본 파일은 직전 내용으로 돌아왔다")
        self.assertEqual(self.snap().seeds, tf.load_seeds(self.paths).value)
        self.assertEqual(self.leftovers(), [])
        self.assert_retry_works()

    def test_when_even_the_rollback_fails_the_error_says_so_and_the_previous_content_is_still_in_the_backup(self):
        def corrupt(args):
            Path(os.fspath(args[1])).write_bytes(b"{garbage")

        self.injector.when("replace", self.MAIN, after=corrupt)
        self.injector.when("replace", self.MAIN, writing_error(), nth=2)             # 되돌리는 이름 바꾸기도 실패
        with self.assertRaises(AppError) as caught:
            sm.set_state(self.ctx, "ex-2", "active", expected_version=self.snap().version, today=DAY)
        self.assertEqual(caught.exception.code, "FILE_WRITE_FAILED")
        self.assertIn("되돌리지도 못했다", caught.exception.detail)
        bak = self.paths.seeds.with_name(sm.BACKUP_NAME)
        self.assertEqual(json.loads(bak.read_bytes()), json.loads(self.before["topic_engine/seeds.json"]), "직전 내용은 사본에 그대로 있다")
        self.assertEqual(self.leftovers(), [])

    def test_the_lock_is_released_after_every_kind_of_failure(self):
        self.inject("write", self.MAIN + ".tmp")
        self.assertEqual(self.try_save(), "FILE_WRITE_FAILED")
        self.assertFalse((self.ctx.workspace.locks_dir / (sm.LOCK_NAME + ".lock")).exists())


class UnwritableFilesTest(Base):
    """읽기 전용 파일·폴더 — 쓰기 실패가 쉬운 오류가 되고 앱이 죽지 않으며 기존 값이 보존된다(운영체제가 막는 진짜 방법으로)."""

    def setUp(self):
        super().setUp()
        self.put(three())
        self.state("ex-1", "active")
        self.before = self.tree()

    @contextlib.contextmanager
    def read_only(self):
        target = self.paths.seeds if os.name == "nt" else self.paths.folder
        original = stat.S_IMODE(target.stat().st_mode)
        os.chmod(target, stat.S_IREAD if os.name == "nt" else stat.S_IRUSR | stat.S_IXUSR)
        try:
            if os.name != "nt" and os.access(self.paths.folder, os.W_OK):
                self.skipTest("이 환경에서는 쓰기 권한을 빼도 쓸 수 있다(관리자 권한)")
            yield
        finally:
            os.chmod(target, original | stat.S_IWRITE)

    def test_a_read_only_seed_file_cannot_be_replaced_and_stays_as_it_was(self):
        with self.read_only():
            code = code_of(sm.set_state, self.ctx, "ex-2", "active", expected_version=self.snap().version, today=DAY)
        self.assertEqual(code, "FILE_WRITE_FAILED")
        self.assertEqual(self.tree(), self.before)
        self.assertEqual(self.leftovers(), [])
        self.assertEqual(sm.set_state(self.ctx, "ex-2", "active", expected_version=self.snap().version, today=DAY).kind, "saved")

    def test_a_lock_folder_that_cannot_be_made_is_a_plain_error(self):
        blocker = self.root / "locks"
        if blocker.exists():
            for item in blocker.iterdir():
                item.unlink()
            blocker.rmdir()
        blocker.write_bytes(b"not a folder")                                          # `locks` 자리에 파일 — 잠금 파일을 만들 수 없다
        code = code_of(sm.set_state, self.ctx, "ex-2", "active", expected_version=self.snap().version, today=DAY)
        self.assertEqual(code, "FILE_WRITE_FAILED")
        self.assertEqual(self.paths.seeds.read_bytes(), self.before["topic_engine/seeds.json"])


# ---- 잠금·동시 저장 ------------------------------------------------------------------------------------------------------------------------
class ConcurrencyTest(Base):
    def run_pair(self, *, second_wait):
        """창 둘이 같은 판에서 읽고 저장한다: 첫째가 잠금 안(백업을 쓰는 중)에 멈춰 있는 동안 둘째가 저장하려 한다 → (결과들, 처음 읽은 판)."""
        self.put(three())
        seen = self.snap().version
        inside, go = threading.Event(), threading.Event()
        real = sm._backup
        results = {}

        def slow(paths, raw):
            inside.set()
            self.assertTrue(go.wait(15))
            return real(paths, raw)

        def first():
            results["first"] = sm.set_state(self.ctx, "ex-1", "active", expected_version=seen, today=DAY)

        def second():
            try:
                results["second"] = sm.set_state(self.ctx, "ex-2", "active", expected_version=seen, today=DAY, wait=second_wait)
            except AppError as error:
                results["second"] = error.code

        with mock.patch.object(sm, "_backup", slow):
            one = threading.Thread(target=first)
            one.start()
            self.assertTrue(inside.wait(15))
            two = threading.Thread(target=second)
            two.start()
            time.sleep(second_wait + 0.4 if second_wait < 1 else 1.0)                # 둘째가 잠금을 기다리는(또는 포기한) 뒤에 첫째를 푼다
            go.set()
            one.join(20)
            two.join(20)
        return results, seen

    def test_two_windows_saving_from_the_same_read_only_one_is_saved_and_the_other_gets_a_conflict(self):
        results, _seen = self.run_pair(second_wait=10.0)
        self.assertEqual(results["first"].kind, "saved")
        self.assertEqual(results["second"], "STORE_CONFLICT", "잠금을 넘겨받은 뒤 판을 다시 보니 낡았다 — 아무것도 쓰지 않았다")
        states = {item.seed_id: item.state for item in tf.load_seeds(self.paths).value}
        self.assertEqual((states["ex-1"], states["ex-2"]), ("active", "proposed"), "진 쪽의 변경은 파일에 없다(잃어버린 갱신이 아니라 거절)")
        self.assertEqual(self.state("ex-2", "active").kind, "saved", "다시 불러온 뒤에는 저장된다")
        self.assertEqual(self.leftovers(), [])

    def test_a_lock_held_by_another_window_makes_the_save_give_up_without_changing_anything(self):
        results, _seen = self.run_pair(second_wait=0.3)
        self.assertEqual(results["first"].kind, "saved")
        self.assertEqual(results["second"], "TOPIC_STORE_LOCKED")
        self.assertEqual({item.seed_id: item.state for item in tf.load_seeds(self.paths).value}, {"ex-1": "active", "ex-2": "proposed", "ex-3": "proposed"})
        self.assertEqual(self.leftovers(), [])

    def test_a_leftover_lock_of_a_finished_process_is_taken_over(self):
        self.put(three())
        lock = sm.SeedsLock(self.ctx.workspace.locks_dir, sm.LOCK_NAME, now=self.ctx.now)
        lock.acquire()                                                                # 이 잠금을 쥔 채 '프로그램이 죽은' 것처럼 풀지 않는다
        with mock.patch("chanceblog_desktop.service.lock.process_alive", return_value=False):
            saved = sm.set_state(self.ctx, "ex-1", "active", expected_version=self.snap().version, today=DAY, wait=1.0)
        self.assertEqual(saved.kind, "saved")
        self.assertEqual(self.leftovers(), [])

    def test_a_lock_held_by_a_live_process_is_never_taken_over(self):
        self.put(three())
        lock = sm.SeedsLock(self.ctx.workspace.locks_dir, sm.LOCK_NAME, now=self.ctx.now)
        lock.acquire()
        self.addCleanup(lock.release)
        before = {name: data for name, data in self.tree().items() if name.startswith("topic_engine")}
        with mock.patch("chanceblog_desktop.service.lock.process_alive", return_value=True):
            code = code_of(sm.set_state, self.ctx, "ex-1", "active", expected_version=self.snap().version, today=DAY, wait=0.2)
        self.assertEqual(code, "TOPIC_STORE_LOCKED")
        self.assertEqual({name: data for name, data in self.tree().items() if name.startswith("topic_engine")}, before)

    def test_two_real_processes_changing_different_seeds_in_turn_lose_nothing(self):
        self.put([seed("ex-a"), seed("ex-b"), seed("ex-c")])
        child = Path(__file__).resolve().parent / "seed_manage_race_child.py"
        env = dict(os.environ, PYTHONPATH=str(ROOT / "src"), PYTHONUTF8="1")
        count = 6
        procs = [subprocess.Popen([sys.executable, "-X", "utf8", str(child), str(self.tmp), which, str(count)], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
                 for which in ("a", "b")]
        outputs = [proc.communicate(timeout=240) for proc in procs]
        for proc, (_out, err) in zip(procs, outputs, strict=True):
            self.assertEqual(proc.returncode, 0, err[-400:])
        states = {item.seed_id: item.state for item in tf.load_seeds(self.paths).value}
        self.assertEqual(states, {"ex-a": "inactive", "ex-b": "inactive", "ex-c": "proposed"}, "두 프로세스의 마지막 상태가 모두 남았고 건드리지 않은 씨앗은 그대로다")
        self.assertEqual(self.leftovers(), [])
        self.assertEqual(len(tf.load_seeds(self.paths).value), 3)


# ---- 쓰기가 닿는 곳 ----------------------------------------------------------------------------------------------------------------------
class TouchedFilesTest(Base):
    def test_every_write_changes_only_the_files_it_may_touch(self):
        """다른 파일(보관함·채널 프로필·캘린더·글 보관함·설정·연결 설정·사용량 기록)은 바이트까지 그대로다 — 새로 생기거나 바뀌는 것은 씨앗 파일·사본·(지나간) 잠금뿐이다."""
        self.paths.folder.mkdir(parents=True)
        others = {self.paths.database: b"SQLite format 3\0example", self.paths.profiles: json.dumps(channels.profiles_to_dict(channels.default_profiles())).encode("utf-8"), self.paths.calendar: b'{"schema": 1, "entries": []}\n',
                  self.ctx.workspace.store_path: b"example store bytes", self.ctx.workspace.connections_path: b'{"schema": 1}', self.ctx.workspace.quota_path: b'{"schema": 1}'}
        for path, data in others.items():
            path.write_bytes(data)
        self.put(three())
        before = self.tree()
        self.state("ex-1", "active")
        sm.edit_seed(self.ctx, "ex-1", {"priority": True}, expected_version=self.snap().version)
        sm.create_seed(self.ctx, create_fields(), expected_version=self.snap().version, today=DAY)
        sm.set_states(self.ctx, ["ex-2", "ex-3"], "inactive", confirmed=True, expected_count=2, expected_version=self.snap().version, today=DAY)
        after = self.tree()
        changed = {name for name in set(before) | set(after) if before.get(name) != after.get(name)}
        self.assertEqual(changed, {"topic_engine/seeds.json", "topic_engine/seeds.json.bak"})
        for path, data in others.items():
            self.assertEqual(path.read_bytes(), data, path.name)
        self.assertEqual(self.leftovers(), [])

    def test_reading_the_snapshot_writes_nothing_at_all(self):
        self.put(three())
        before = self.tree()
        self.snap()
        self.snap()
        self.assertEqual(self.tree(), before)


# ---- 소스·실제 값 --------------------------------------------------------------------------------------------------------------------------
class SourceRulesTest(unittest.TestCase):
    SERVICE = ROOT / "src" / "chanceblog_desktop" / "service" / "seed_manage.py"
    REAL_BLOGS = ("ssae" + "ssace", "shine" + "5652", "스마트" + "프라이싱", "스마트" + "초이스", "실전" + "노트", "디지털" + "찬스")
    REAL_LIST_MARKS = ("초기 Seed " + "130개 제안", "확인 부탁 " + "5건", "초기_Seed_" + "130")

    def test_the_module_has_no_low_level_write_calls_of_its_own_and_writes_only_through_write_json(self):
        import ast
        tree = ast.parse(self.SERVICE.read_text(encoding="utf-8"))
        calls = [ast.unparse(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)]
        for forbidden in ("os.open", "os.write", "os.fsync", "os.replace", "os.rename", "os.remove", "open", "shutil.copy", "shutil.move"):
            self.assertNotIn(forbidden, calls)
        for name in ("write_text", "write_bytes", "unlink", "mkdir", "touch", "rmdir", "chmod"):
            self.assertFalse([call for call in calls if call.endswith("." + name)], name)
        self.assertEqual(calls.count("write_json"), 5, "본 파일 쓰기 하나·사본 하나·사본 되돌리기 하나·본 파일 되돌리기 둘 — 모두 write_json")

    def test_the_only_calls_that_write_are_inside_the_commit_path(self):
        import ast
        tree = ast.parse(self.SERVICE.read_text(encoding="utf-8"))
        inside = {}
        for function in [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]:
            for node in ast.walk(function):
                if isinstance(node, ast.Call) and ast.unparse(node.func) == "write_json":
                    inside[function.name] = inside.get(function.name, 0) + 1
        self.assertEqual(inside, {"_backup": 1, "_undo_backup": 1, "_restore": 2, "_commit": 1})

    def test_every_public_write_goes_through_the_one_commit_path_and_no_other_function_calls_it(self):
        import ast
        tree = ast.parse(self.SERVICE.read_text(encoding="utf-8"))
        users = {}
        for function in [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]:
            for node in ast.walk(function):
                if isinstance(node, ast.Call) and ast.unparse(node.func) == "_commit":
                    users[function.name] = users.get(function.name, 0) + 1
        self.assertEqual(users, {"set_state": 1, "set_states": 1, "edit_seed": 1, "create_seed": 1, "apply_import": 1})

    def test_the_commit_path_checks_the_guard_the_key_shape_and_the_version_before_the_first_write(self):
        import ast
        tree = ast.parse(self.SERVICE.read_text(encoding="utf-8"))
        plan = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "_plan")
        names = [ast.unparse(node.func) for node in ast.walk(plan) if isinstance(node, ast.Call)]
        for needed in ("_guard", "_refuse_key_shape", "sd.seeds_to_dict", "tbackup.check_json_bytes", "_conflict"):
            self.assertIn(needed, names)

    def test_no_real_seed_list_or_blog_name_is_written_anywhere_in_the_repository(self):
        skip = {".git", "vendor", "__pycache__", ".venv"}
        found = []
        for path in ROOT.rglob("*"):
            if not path.is_file() or (set(path.relative_to(ROOT).parts) & skip):
                continue
            relative = path.relative_to(ROOT).as_posix()
            if path.name == "seeds.json" or path.name.startswith("seed_proposals") or "Seed_130" in path.name:
                found.append(f"{relative}: 실제 씨앗 목록 파일")
            if path.suffix not in {".md", ".py", ".txt", ".json", ".yml", ".yaml", ".toml", ".example"}:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            found += [f"{relative}: {value[:2]}…" for value in (*self.REAL_BLOGS, *self.REAL_LIST_MARKS) if value in text]
        self.assertEqual(found, [], "실제 씨앗 목록과 블로그 이름은 사용자 데이터에만 둔다(저장소에는 가짜 씨앗뿐)")


if __name__ == "__main__":
    unittest.main()
