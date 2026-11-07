"""키 연결 화면의 실제 공급자(`ui/keys_adapter.py`, P4f) 시험 — 실제 서비스(`service/connections.py`)와 실제 임시 데이터 폴더·가짜 보관소(`MemoryStore` — 진짜 자격 증명 관리자는 부르지 않는다)로 돈다. PySide6 가 없어도 돈다.

지키는 것:
  1) 읽기(`load_connections`)는 파일도 보관소도 바꾸지 않고 키 값을 꺼내지도 않는다(`exists` 만 묻는다 — `get`·`tail` 0번). 새로 알리는 값은 항목 번호·제공자·마지막 성공·확인 결과·순서·제공자 상한·입력 칸·저장소 사용 여부뿐이다.
  2) 쓰는 길은 서비스 함수 여섯뿐이고(소스 규칙) 각 동작이 서비스의 규칙대로 된다. 서비스 오류는 **종류**와 **칸 문제 이름** 으로만 바뀌고 문장은 정해진 쉬운 말이다.
  3) **등록·삭제 도중 실패해도 안전하다**: 파일 쓰기가 실패하면 방금 넣은 키가 보관소에서 지워지고, 지우기까지 실패하면 '키가 보관소에 남았을 수 있다' 고 알린다. 삭제 도중 파일 쓰기가 실패하면 '항목은 있는데 키가 없는' 상태가 되고, 화면은 '바뀐 것은 없어요' 라고 하지 않고 목록을 바로 다시 읽어 그 행을 '키를 찾지 못했어요' 로 보이며 다시 지울 수 있다(독립 검증 M1).
  4) 키가 어디에도 없다 — 어떤 길로 끝나도 통은 비고, 앱이 가진 구조·실패 객체의 글과 호출 흔적·데이터 폴더의 모든 파일에 가짜 키와 그 조각이 0건이다(보관소만 키를 가진다 — 그것이 '보관소만' 의 증명이다).
  5) 호출 코드가 없는 용도는 '준비 중' 이고, 이용 약관 확인 전 용도는 시험 함수가 있어도 부르지 않는다. 시험에서 실제 네트워크를 부르는 일은 없다.
"""
import ast
import errno
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
import key_leak_support as leak  # noqa: E402
import service_support as ss  # noqa: E402

from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.security import keystore as ks  # noqa: E402
from chanceblog_desktop.service import connections as cn  # noqa: E402
from chanceblog_desktop.service import context as cx  # noqa: E402
from chanceblog_desktop.ui import adapters, keys_adapter  # noqa: E402
from chanceblog_desktop.ui.core import app_state, jobs, keys, services  # noqa: E402
from chanceblog_desktop.ui.core.text import T  # noqa: E402

KEY = leak.make_key("a")
OTHER = leak.make_key("b")
THIRD = leak.make_key("c")
ALNUM = "".join(ch for ch in KEY if ch.isalnum())                                  # NAVER API HUB 칸은 영문·숫자와 `_ -` 만 받는다
PLAIN = "ghijklmnopqrstuvwxyz"                                                      # 숫자가 없어 '키처럼 보이지' 않는 값 — 이름에 든 값 검사(`value`)를 따로 시험한다
NEEDLES = leak.needles(KEY, OTHER, THIRD, ALNUM, PLAIN)
UI = ROOT / "src" / "chanceblog_desktop" / "ui"


class BrokenStore(ks.MemoryStore):
    """실패를 흉내 내는 가짜 보관소 — 플래그를 켜면 그 일이 KEY_STORE_UNAVAILABLE 로 실패한다. `gets` 는 값을 꺼낸 횟수."""

    def __init__(self):
        super().__init__()
        self.fail_write = self.fail_delete = self.fail_read = False
        self.gets = 0

    def get(self, ref):
        self.gets += 1
        return super().get(ref)

    def _problem(self):
        return AppError("KEY_STORE_UNAVAILABLE", detail="시험용 실패")

    def _write(self, ref, raw):
        if self.fail_write:
            raise self._problem()
        super()._write(ref, raw)

    def _read(self, ref):
        if self.fail_read:
            raise self._problem()
        return super()._read(ref)

    def _delete(self, ref):
        if self.fail_delete:
            raise self._problem()
        return super()._delete(ref)


def box_of(purpose, key=KEY):
    box = keys.SecretBox()
    for name, _label, _min in services._FIELD_TABLE[purpose]:
        box.put(name, key)
    return box


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.ctx = ss.make_ctx(self.tmp, clock=ss.Clock())
        self.store = BrokenStore()
        self.ctx.keystore = self.store
        self.provider = self.make_provider()

    def make_provider(self, **kwargs):
        return keys_adapter.ServiceKeysProvider(None, context_factory=lambda data_dir=None: self.ctx, **kwargs)

    def load(self, provider=None):
        return (provider or self.provider).load_connections(lambda *_: None, lambda: False)

    def info(self, purpose, provider=None):
        return next(item for item in self.load(provider).purposes if item.key == purpose)

    def add(self, purpose="ai_assist", name="가", key=KEY, provider="", terms=False, **kwargs):
        return self.provider.add_key(purpose, provider or services._PROVIDER_TABLE[purpose][0][0], name, box_of(purpose, key), terms, lambda *_: None, lambda: False, **kwargs)

    def file_bytes(self):
        path = self.ctx.workspace.connections_path
        return path.read_bytes() if path.exists() else None

    def folder_state(self):
        root = self.ctx.workspace.root
        return {path.relative_to(root).as_posix(): path.read_bytes() for path in sorted(root.rglob("*")) if path.is_file()} if root.exists() else {}

    def failing(self, call, *args, **kwargs):
        """호출이 `KeyFailure` 로 끝나야 한다 → 실패. 호출 흔적(`__traceback__`)이 **그대로 붙은** 실패를 돌려준다 — `assertRaises` 의 `.exception` 은 흔적을 떼어 버려서 프레임 지역 변수에 키가 남는지 보는
        검사(`assert_clean`)가 빈 검사가 된다(변이 시험에서 '꺼낸 글 dict 를 안 비워도 시험이 통과' 하는 것으로 찾았다)."""
        try:
            call(*args, **kwargs)
        except keys.KeyFailure as failure:
            return failure
        self.fail("KeyFailure 로 끝나야 한다")

    def assert_clean(self, failure, alias=None):
        """실패에 키가 없다 — 글·호출 흔적의 프레임 지역 변수까지(공급자·가짜 보관소는 키를 일부러 담고 있으니 제외). `alias` 는 **시험이 별칭으로 일부러 넘긴 키 모양 글**(받은 인자라 어댑터 자신의 매개변수에 있는 것은 당연하다 —
        실제 앱에서는 키처럼 보이는 별칭이 컨트롤러에서 막혀 어댑터까지 오지 않는다)이다."""
        skip = (self.provider, self.store, self.ctx) + ((alias,) if alias else ())
        self.assertEqual(leak.error_hits(failure, NEEDLES, skip=skip), [])
        self.assertIsNone(failure.__context__)
        self.assertIsNone(failure.__cause__)


class ReadTest(Base):
    def test_the_read_fills_the_new_values_from_the_service_table_and_never_asks_for_a_key(self):
        self.add("ai_assist", "가")
        self.add("image_provider", "언스", provider="unsplash")
        self.store.gets = 0
        data = self.load()
        self.assertEqual(self.store.gets, 0, "값을 꺼내지 않는다(`exists` 만 묻는다)")
        self.assertTrue(data.store_ready)
        by_key = {info.key: info for info in data.purposes}
        for key, spec in cn.PURPOSES.items():
            if key not in by_key:
                continue
            info = by_key[key]
            self.assertEqual([(item.key, item.label, item.cap, item.needs_terms) for item in info.providers], [(item.key, item.label, spec.entry_cap(item.key), item.second_key_needs_terms) for item in spec.providers] if spec.takes_keys else [], key)
            self.assertEqual([(item.name, item.label, item.min_len) for item in info.fields], [(item.name, item.label, item.min_len) for item in spec.fields], key)
        entry = by_key["ai_assist"].entries[0]
        self.assertEqual((entry.name, entry.state, entry.key_found, entry.provider, entry.check, entry.last_ok, entry.order), ("가", "active", True, "gemini", "", "", 1))
        self.assertRegex(entry.ref, "^[0-9a-f]{32}$")
        self.assertEqual({key: (info.can_test, info.test_blocked) for key, info in by_key.items()},
                         {"naver_apihub": (False, "terms"), "naver_searchad": (False, ""), "image_provider": (False, ""), "ai_assist": (False, ""), "blogger": (False, ""), "github_repo": (False, "")})

    def test_the_read_leaves_every_file_and_every_stored_key_as_it_was(self):
        for case in ("빈 폴더", "항목 둘"):
            with self.subTest(case):
                if case == "항목 둘":
                    self.add("ai_assist", "가")
                    self.add("image_provider", "언스", provider="unsplash")
                before, refs = self.folder_state(), self.store.list_refs()
                for _ in range(3):
                    self.load()
                self.assertEqual((self.folder_state(), self.store.list_refs()), (before, refs))

    def test_an_entry_whose_key_is_gone_is_shown_as_not_found_and_the_rest_still_reads(self):
        self.add("ai_assist", "가")
        ref = self.info("ai_assist").entries[0].ref
        self.store.delete("ai_assist:" + ref)
        self.assertFalse(self.info("ai_assist").entries[0].key_found)

    def test_an_unavailable_key_store_is_a_state_not_an_error(self):
        ctx = self.ctx
        ctx.keystore = None
        failing = mock.Mock(side_effect=AppError("KEY_STORE_UNAVAILABLE", detail="시험용 실패"))
        with mock.patch.object(type(ctx), "get_keystore", failing):
            data = self.load()
        self.assertFalse(data.store_ready)
        self.assertIn("keystore", data.partial)
        self.assertEqual(len(data.purposes), 6)

    def test_a_read_only_provider_has_no_tester_and_the_base_class_never_writes(self):
        provider = adapters.ServiceConnectionsProvider(None, context_factory=lambda data_dir=None: self.ctx)
        self.assertFalse(isinstance(provider, keys.KeysWriter))
        self.assertTrue(all(not info.can_test for info in self.load(provider).purposes))

    def test_the_real_home_provider_pairs_the_writing_provider_and_the_sample_pairs_the_memory_one(self):
        paired = adapters.ServiceHomeProvider(None, context_factory=lambda data_dir=None: self.ctx).connections_provider()
        self.assertIsInstance(paired, keys_adapter.ServiceKeysProvider)
        self.assertIsInstance(paired, adapters.ServiceConnectionsProvider)
        self.assertIsInstance(services.FakeHomeProvider().connections_provider(), keys.FakeKeysProvider)


class AddTest(Base):
    def test_a_key_goes_to_the_store_and_only_names_and_states_go_to_the_file(self):
        box = box_of("ai_assist")
        outcome = self.provider.add_key("ai_assist", "gemini", "내 별칭", box, False, lambda *_: None, lambda: False)
        self.assertEqual(outcome.kind, "added")
        self.assertEqual(len(box), 0)
        ref = self.info("ai_assist").entries[0].ref
        self.assertEqual(self.store.get("ai_assist:" + ref).reveal("key"), KEY)                       # 보관소만 키를 가진다
        self.assertEqual(leak.file_hits(self.ctx.workspace.root, NEEDLES), [])
        stored = json.loads(self.file_bytes())
        self.assertEqual(sorted(stored["entries"][0]), sorted(["bucket", "checked_at", "check_result", "created_at", "entry_id", "last_ok_at", "name", "order", "project", "provider", "purpose", "state", "terms_ack_at"]))
        self.assertEqual(leak.graph_hits(self.provider, NEEDLES, skip=(self.store, self)), [])
        self.assertNotEqual(leak.graph_hits(self.store, NEEDLES), [], "시험 도구가 보관소 안의 키는 찾아내는지(대조군)")

    def test_the_alias_is_sent_as_given_by_the_screen_and_the_provider_name_selects_the_entry_group(self):
        self.add("image_provider", "언스", provider="unsplash")
        self.add("image_provider", "펙스", key=OTHER, provider="pexels")
        info = self.info("image_provider")
        self.assertEqual([(item.name, item.provider, item.order) for item in info.entries], [("언스", "unsplash", 1), ("펙스", "pexels", 2)])

    def test_each_service_error_becomes_a_plain_kind_and_never_repeats_the_key(self):
        self.add("image_provider", "언스", provider="unsplash")
        self.add("ai_assist", "가")
        cases = {
            "limit": lambda: self.add("image_provider", "둘", key=OTHER, provider="unsplash", terms=True),
            "terms": lambda: self.add("ai_assist", "나", key=OTHER),
            "duplicate-name": lambda: self.add("ai_assist", "가", key=OTHER, terms=True),
            "duplicate-value": lambda: self.add("ai_assist", "나", key=KEY, terms=True),
            "invalid-short": lambda: self.add("ai_assist", "나", key=OTHER[:10], terms=True),
            "invalid-chars": lambda: self.add("ai_assist", "나", key="한글키값한글키값한글키값한글키값", terms=True),
            "invalid-hidden": lambda: self.add("ai_assist", "나", key=OTHER[:12] + " " + OTHER[12:], terms=True),
            "invalid-alias": lambda: self.add("ai_assist", OTHER, key=OTHER[:20], terms=True),
        }
        expected = {"limit": ("limit", {}), "terms": ("terms", {}), "duplicate-name": ("duplicate", {"name": "duplicate"}), "duplicate-value": ("duplicate", {"value": "duplicate"}),
                    "invalid-short": ("invalid", {"key": "min:16"}), "invalid-chars": ("invalid", {"key": "chars"}), "invalid-hidden": ("invalid", {"key": "hidden"}), "invalid-alias": ("invalid", {"name": "keyish"})}
        for name, call in cases.items():
            with self.subTest(name):
                before, refs = self.folder_state(), self.store.list_refs()
                failure = self.failing(call)
                self.assertEqual((failure.kind, failure.problems), expected[name], name)
                self.assertEqual(failure.user_message, keys.failure_text(failure.kind, problems=failure.problems))
                self.assert_clean(failure, alias=OTHER if name == "invalid-alias" else None)
                self.assertEqual((self.folder_state(), self.store.list_refs()), (before, refs), "거절된 일은 파일도 보관소도 바꾸지 않는다")

    def test_the_boxes_are_empty_whatever_the_ending(self):
        box = box_of("ai_assist")
        self.provider.add_key("ai_assist", "gemini", "가", box, False, lambda *_: None, lambda: False)
        self.assertEqual(len(box), 0)
        short = box_of("ai_assist", OTHER[:10])
        self.failing(self.provider.add_key, "ai_assist", "gemini", "나", short, True, lambda *_: None, lambda: False)
        self.assertEqual(len(short), 0)
        cancelled = box_of("ai_assist", OTHER)
        with self.assertRaises(jobs.JobCancelled):
            self.provider.add_key("ai_assist", "gemini", "다", cancelled, True, lambda *_: None, lambda: True)
        self.assertEqual((len(cancelled), len(self.store.list_refs())), (0, 1), "취소는 통을 비우고 아무것도 쓰지 않는다")
        crashed = box_of("ai_assist", OTHER)
        with mock.patch.object(cn, "add_entry", side_effect=ValueError("내용 " + OTHER)):
            failure = self.failing(self.provider.add_key, "ai_assist", "gemini", "라", crashed, True, lambda *_: None, lambda: False)
        self.assertEqual((failure.kind, failure.code, len(crashed)), ("other", "ValueError", 0))
        self.assert_clean(failure)

    def test_a_failed_metadata_write_removes_the_key_that_was_just_stored(self):
        before = self.folder_state()
        with mock.patch.object(cn, "write_json", side_effect=AppError("DISK_FULL", {})):
            failure = self.failing(self.add, "ai_assist", "가")
        self.assertEqual((failure.kind, failure.leftover), ("disk", False))
        self.assertEqual((self.store.list_refs(), self.folder_state()), ([], before), "키는 보관소에도 파일에도 남지 않는다")
        self.assert_clean(failure)
        self.add("ai_assist", "가")                                                                  # 같은 일을 다시 하면 저장된다
        self.assertEqual(len(self.store.list_refs()), 1)

    def test_when_even_the_cleanup_fails_the_screen_is_told_the_key_may_be_left_in_the_store(self):
        self.store.fail_delete = True
        with mock.patch.object(cn, "write_json", side_effect=AppError("FILE_WRITE_FAILED", {})):
            failure = self.failing(self.add, "ai_assist", "가")
        self.assertEqual((failure.kind, failure.leftover), ("store", True))
        self.assertEqual(failure.user_message, T["keys_fail_leftover"])
        self.assertEqual(len(self.store.list_refs()), 1, "정리하지 못한 키가 보관소에 남았음을 숨기지 않는다")
        self.assert_clean(failure)
        self.assertTrue(str(cn.ROLLBACK_FAILED_DETAIL).startswith("항목을 저장하지 못했고"))

    def test_a_failing_store_means_nothing_is_written_and_a_broken_file_is_not_written_over(self):
        self.store.fail_write = True
        failure = self.failing(self.add, "ai_assist", "가")
        self.assertEqual((failure.kind, self.file_bytes()), ("store", None))
        self.assert_clean(failure)
        self.store.fail_write = False
        self.ctx.workspace.connections_path.parent.mkdir(parents=True, exist_ok=True)
        self.ctx.workspace.connections_path.write_text("{ 깨진 파일", encoding="utf-8")
        before = self.folder_state()
        failure = self.failing(self.add, "ai_assist", "가")
        self.assertEqual(failure.kind, "corrupt")
        self.assertEqual((self.folder_state(), self.store.list_refs()), (before, []))
        self.assert_clean(failure)

    def test_a_busy_lock_and_a_missing_data_folder_are_plain_failures(self):
        with mock.patch.object(cn.KeysLock, "acquire_waiting", side_effect=AppError("KEYS_BUSY", {"작업": "연결 설정을 바꾸다"})):
            failure = self.failing(self.add, "ai_assist", "가")
        self.assertEqual((failure.kind, self.store.list_refs()), ("busy", []))
        missing = keys_adapter.ServiceKeysProvider(str(self.tmp / "없는 폴더"), context_factory=lambda data_dir=None: self.ctx)
        failure = self.failing(missing.add_key, "ai_assist", "gemini", "가", box_of("ai_assist"), False, lambda *_: None, lambda: False)
        self.assertEqual((failure.kind, failure.code, failure.user_message), ("io", "DATA_DIR_NOT_FOUND", T["data_dir_missing"]))
        self.assertEqual(self.store.list_refs(), [])


class ChangeTest(Base):
    def setUp(self):
        super().setUp()
        self.add("ai_assist", "가")
        self.add("ai_assist", "나", key=OTHER, terms=True)
        self.first, self.second = [item.ref for item in self.info("ai_assist").entries]

    def call(self, name, *args):
        return getattr(self.provider, name)("ai_assist", *args, lambda *_: None, lambda: False)

    def test_remove_deletes_the_stored_key_first_and_renumbers_the_rest(self):
        outcome = self.call("remove_key", self.first)
        self.assertEqual((outcome.kind, outcome.ref), ("removed", self.first))
        self.assertEqual(self.store.list_refs(), ["ai_assist:" + self.second])
        self.assertEqual([(item.name, item.order) for item in self.info("ai_assist").entries], [("나", 1)])

    def test_a_failure_while_removing_leaves_an_entry_without_a_key_that_can_be_removed_again(self):
        with mock.patch.object(cn, "write_json", side_effect=AppError("DISK_FULL", {})):
            failure = self.failing(self.call, "remove_key", self.first)
        self.assertEqual(failure.kind, "disk")
        entries = {item.ref: item for item in self.info("ai_assist").entries}
        self.assertFalse(entries[self.first].key_found, "항목은 있는데 키가 없는 상태가 화면에 보인다")
        self.assertTrue(entries[self.second].key_found)
        self.assertEqual(self.call("remove_key", self.first).kind, "removed")                        # 다시 지울 수 있다(보관소 지우기는 멱등)
        self.assertEqual([item.name for item in self.info("ai_assist").entries], ["나"])

    def test_a_failing_store_does_not_remove_the_entry(self):
        self.store.fail_delete = True
        failure = self.failing(self.call, "remove_key", self.first)
        self.assertEqual(failure.kind, "store")
        self.assertEqual(len(self.info("ai_assist").entries), 2)
        self.store.fail_delete = False
        self.assertEqual(self.call("remove_key", self.first).kind, "removed")

    def test_an_entry_that_is_already_gone_is_a_plain_not_found(self):
        failure = self.failing(self.call, "remove_key", "ab" * 16)
        self.assertEqual(failure.kind, "notfound")
        for call in (lambda: self.call("rename_key", "ab" * 16, "이름"), lambda: self.call("set_key_state", "ab" * 16, "off"), lambda: self.call("move_key", "ab" * 16, 1)):
            self.assertEqual(self.failing(call).kind, "notfound")

    def test_state_and_rename_change_only_their_own_field(self):
        before = {item.ref: item for item in self.info("ai_assist").entries}
        self.assertEqual(self.call("set_key_state", self.first, "standby").kind, "state")
        self.assertEqual(self.call("set_key_state", self.first, "standby").kind, "unchanged")
        self.assertEqual(self.call("rename_key", self.second, "새 별칭").kind, "renamed")
        self.assertEqual(self.call("rename_key", self.second, "새 별칭").kind, "unchanged")
        after = {item.ref: item for item in self.info("ai_assist").entries}
        self.assertEqual(after[self.first].state, "standby")
        self.assertEqual((after[self.first].name, after[self.second].name, after[self.second].state), (before[self.first].name, "새 별칭", before[self.second].state))
        self.assertEqual(sorted(self.store.list_refs()), sorted(f"ai_assist:{ref}" for ref in (self.first, self.second)), "값은 그대로")

    def test_a_rename_with_a_bad_name_is_a_plain_alias_problem_and_a_key_in_the_name_is_refused(self):
        self.provider.add_key("image_provider", "unsplash", "평범한 값", box_of("image_provider", PLAIN), False, lambda *_: None, lambda: False)
        plain_ref = next(item for item in self.info("image_provider").entries).ref
        for ref, purpose, name, expected in ((self.first, "ai_assist", "나", {"name": "duplicate"}), (self.first, "ai_assist", "", {"name": "empty"}), (self.first, "ai_assist", KEY, {"name": "keyish"}),
                                             (plain_ref, "image_provider", "앞" + PLAIN + "뒤", {"name": "value"})):
            with self.subTest(name=name[:6]):
                before = self.folder_state()
                failure = self.failing(getattr(self.provider, "rename_key"), purpose, ref, name, lambda *_: None, lambda: False)
                self.assertEqual((failure.kind, failure.problems), ("duplicate" if expected == {"name": "duplicate"} else "invalid", expected))
                self.assertEqual(self.folder_state(), before)
                self.assert_clean(failure, alias=name)

    def test_a_rename_without_a_readable_store_changes_nothing(self):
        self.store.fail_read = True
        before = self.folder_state()
        failure = self.failing(self.call, "rename_key", self.first, "새 별칭")
        self.assertEqual((failure.kind, self.folder_state()), ("store", before))

    def test_move_swaps_neighbours_and_stops_at_the_edges(self):
        self.assertEqual(self.call("move_key", self.second, -1).kind, "moved")
        self.assertEqual([item.name for item in self.info("ai_assist").entries], ["나", "가"])
        self.assertEqual(self.call("move_key", self.second, -1).kind, "unchanged")
        self.assertEqual(self.call("move_key", self.first, 1).kind, "unchanged")
        self.assertEqual(self.call("move_key", self.first, -1).kind, "moved")
        self.assertEqual([item.name for item in self.info("ai_assist").entries], ["가", "나"])

    def test_every_write_on_a_broken_file_stops_and_leaves_it_alone(self):
        self.ctx.workspace.connections_path.write_text("{ 깨진", encoding="utf-8")
        before = self.folder_state()
        for call in (lambda: self.call("remove_key", self.first), lambda: self.call("set_key_state", self.first, "off"), lambda: self.call("rename_key", self.first, "새"), lambda: self.call("move_key", self.first, 1)):
            self.assertEqual(self.failing(call).kind, "corrupt")
        self.assertEqual(self.folder_state(), before)

    def test_a_cancelled_job_writes_nothing(self):
        before = self.folder_state()
        for name, args in (("remove_key", (self.first,)), ("set_key_state", (self.first, "off")), ("rename_key", (self.first, "새")), ("move_key", (self.first, 1)), ("test_key", (self.first,))):
            with self.assertRaises(jobs.JobCancelled):
                getattr(self.provider, name)("ai_assist", *args, lambda *_: None, lambda: True)
        self.assertEqual(self.folder_state(), before)


class TestKeyTest(Base):
    def registry(self, *implemented):
        import dataclasses
        registry = dict(cn.PURPOSES)
        for key in implemented:
            registry[key] = dataclasses.replace(cn.PURPOSES[key], implemented=True)
        return registry

    def test_a_purpose_without_calling_code_says_getting_ready_and_calls_nothing(self):
        calls = []
        provider = self.make_provider(tester=lambda spec, entry, fields: calls.append(entry.ref))
        self.add("ai_assist", "가")
        ref = self.info("ai_assist", provider).entries[0].ref
        outcome = provider.test_key("ai_assist", ref, lambda *_: None, lambda: False)
        self.assertEqual((outcome.kind, outcome.result), ("tested", "not_ready"))
        self.assertEqual(calls, [])
        self.assertFalse(self.info("ai_assist", provider).can_test)

    def test_with_no_tester_at_all_an_implemented_purpose_still_says_getting_ready(self):
        provider = self.make_provider(registry=self.registry("image_provider"))
        self.add("image_provider", "언스", provider="unsplash")
        ref = self.info("image_provider", provider).entries[0].ref
        self.assertEqual(provider.test_key("image_provider", ref, lambda *_: None, lambda: False).result, "not_ready")

    def test_an_implemented_purpose_with_a_tester_is_tested_once_and_the_result_is_recorded(self):
        seen = []

        def tester(spec, entry, fields):
            seen.append((spec.key, entry.ref, fields.names()))
            return cn.ProviderResult("ok")
        provider = self.make_provider(registry=self.registry("image_provider"), tester=tester)
        self.add("image_provider", "언스", provider="unsplash")
        info = self.info("image_provider", provider)
        self.assertTrue(info.can_test)
        outcome = provider.test_key("image_provider", info.entries[0].ref, lambda *_: None, lambda: False)
        self.assertEqual((outcome.kind, outcome.result), ("tested", "ok"))
        self.assertEqual(seen, [("image_provider", "image_provider:" + info.entries[0].ref, ("access_key",))])           # 시험 함수는 서비스의 항목(`Entry.ref` = 용도:번호)과 값 묶음을 받는다
        entry = self.info("image_provider", provider).entries[0]
        self.assertEqual(entry.check, "ok")
        self.assertRegex(entry.last_ok, "^2026-11-02T")
        again = provider.test_key("image_provider", info.entries[0].ref, lambda *_: None, lambda: False)
        self.assertEqual((again.result, again.wait > 0, len(seen)), ("too_soon", True, 1), "같은 키는 60초 안에 다시 시험하지 않는다")

    def test_each_tester_answer_becomes_a_plain_result(self):
        for answer, expected, check in (("auth_failed", "auth_failed", "auth_failed"), ("rate_limited", "rate_limited", "error"), ("error", "error", "error"), ("뭔가 이상한 값", "error", "error")):
            with self.subTest(answer=answer):
                tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
                self.addCleanup(tmp.cleanup)
                ctx = ss.make_ctx(tmp.name, clock=ss.Clock())
                provider = keys_adapter.ServiceKeysProvider(None, context_factory=lambda data_dir=None, ctx=ctx: ctx, registry=self.registry("image_provider"), tester=lambda *_args, answer=answer: cn.ProviderResult(answer))
                provider.add_key("image_provider", "unsplash", "언스", box_of("image_provider"), False, lambda *_: None, lambda: False)
                ref = next(item for item in provider.load_connections(lambda *_: None, lambda: False).purposes if item.key == "image_provider").entries[0].ref
                outcome = provider.test_key("image_provider", ref, lambda *_: None, lambda: False)
                self.assertEqual(outcome.result, expected)
                self.assertEqual(next(item for item in provider.load_connections(lambda *_: None, lambda: False).purposes if item.key == "image_provider").entries[0].check, check)

    def test_a_tester_that_crashes_is_a_plain_error_and_never_repeats_the_key(self):
        def tester(spec, entry, fields):
            raise RuntimeError("값 " + fields.reveal("access_key"))
        provider = self.make_provider(registry=self.registry("image_provider"), tester=tester)
        self.add("image_provider", "언스", provider="unsplash")
        ref = self.info("image_provider", provider).entries[0].ref
        outcome = provider.test_key("image_provider", ref, lambda *_: None, lambda: False)
        self.assertEqual((outcome.kind, outcome.result), ("tested", "error"))
        self.assertEqual(leak.graph_hits(outcome, NEEDLES), [])

    def test_terms_pending_purposes_never_call_the_tester_even_when_implemented(self):
        calls = []
        provider = self.make_provider(registry=self.registry("naver_apihub"), tester=lambda *_args: calls.append(1) or cn.ProviderResult("ok"))
        provider.add_key("naver_apihub", "", "허브", box_of("naver_apihub", ALNUM), False, lambda *_: None, lambda: False)
        info = next(item for item in provider.load_connections(lambda *_: None, lambda: False).purposes if item.key == "naver_apihub")
        self.assertEqual((info.implemented, info.can_test, info.test_blocked), (True, False, "terms"))
        outcome = provider.test_key("naver_apihub", info.entries[0].ref, lambda *_: None, lambda: False)
        self.assertEqual((outcome.result, calls), ("not_ready", []))

    def test_a_missing_stored_key_is_reported_before_any_call(self):
        calls = []
        provider = self.make_provider(registry=self.registry("image_provider"), tester=lambda *_args: calls.append(1) or cn.ProviderResult("ok"))
        self.add("image_provider", "언스", provider="unsplash")
        ref = self.info("image_provider", provider).entries[0].ref
        self.store.delete("image_provider:" + ref)
        outcome = provider.test_key("image_provider", ref, lambda *_: None, lambda: False)
        self.assertEqual((outcome.result, calls), ("no_value", []))


class FullFlowTest(Base):
    """화면 상태(`AppState`·컨트롤러·작업 틀)와 실제 어댑터·서비스를 이어 한 번 끝까지 — 키가 어디에도 없다."""

    def env(self):
        runner = jobs.JobRunner()
        state = app_state.AppState(services.FakeHomeProvider(), connections=self.provider, runner=runner)
        state.apply_connections(self.load())
        return runner, state

    def drive(self, state, starter):
        results = []
        status, job = starter(on_done=lambda result, _p: results.append(("ok", result)), on_error=lambda failure, _p: results.append(("err", failure)), on_cancel=lambda _p: results.append(("cancel", None)))
        if status != "started":
            return status, None
        job.join(10)
        kind, value = results[0]
        (state.keys.apply_write_ok if kind == "ok" else state.keys.apply_write_failed)(value)
        state.apply_connections(self.load())
        return status, (kind, value)

    def test_a_whole_session_leaves_the_key_only_in_the_store(self):
        runner, state = self.env()
        controller = state.keys
        self.assertTrue(controller.writable and controller.store_ready())
        draft = controller.open_register("ai_assist")
        draft.set_alias("내 별칭")
        self.assertTrue(draft.go_confirm({}))
        shown = [draft.vm()]
        self.drive(state, lambda **cb: controller.start_add("ai_assist", draft.provider, draft.alias, box_of("ai_assist"), False, **cb))
        self.drive(state, lambda **cb: controller.start_add("ai_assist", "gemini", "둘째", box_of("ai_assist", OTHER), True, **cb))
        self.drive(state, lambda **cb: controller.start_add("ai_assist", "gemini", "짧음", box_of("ai_assist", OTHER[:10]), True, **cb))          # 실패
        first, second = [item.ref for item in controller.info("ai_assist").entries]
        self.drive(state, lambda **cb: controller.start_move("ai_assist", second, -1, **cb))
        self.drive(state, lambda **cb: controller.start_rename("ai_assist", first, "새 별칭", **cb))
        self.drive(state, lambda **cb: controller.start_state("ai_assist", first, "standby", **cb))
        self.assertEqual(self.drive(state, lambda **cb: controller.start_test("ai_assist", first, **cb))[0], "unavailable")            # 호출 코드가 없는 용도 — 시험은 시작되지 않는다
        shown += [state.settings_view(), controller.notice, controller.row_notes]
        self.drive(state, lambda **cb: controller.start_remove("ai_assist", second, **cb))
        runner.join_all(5)
        self.assertEqual(leak.graph_hits((state, shown), NEEDLES, skip=(self.store, self)), [], "앱이 가진 모든 구조")
        self.assertEqual(leak.file_hits(self.ctx.workspace.root, NEEDLES), [], "데이터 폴더의 모든 파일")
        self.assertEqual([item.name for item in controller.info("ai_assist").entries], ["새 별칭"])
        self.assertEqual(self.store.get("ai_assist:" + first).reveal("key"), KEY)

    # ---- 독립 검증 M1: 삭제 도중 파일 쓰기가 실패하면 — 키 저장소의 키는 이미 지워졌을 수 있다 ----------------------------------------------------
    REMOVE_IO = ("키를 지우다가 연결 설정 파일에 저장하지 못했어요. 키가 이미 지워졌을 수도 있어서 목록을 다시 읽어 드릴게요. 그 줄에 '보관소에서 이 키를 찾지 못했어요' 가 보이면 삭제를 한 번 더 눌러 정리해 주세요. 키가 그대로면 잠시 뒤 다시 지워 주세요.")
    REMOVE_DISK = ("키를 지우다가 디스크 공간이 모자라 저장하지 못했어요. 키가 이미 지워졌을 수도 있어서 목록을 다시 읽어 드릴게요. 그 줄에 '보관소에서 이 키를 찾지 못했어요' 가 보이면 삭제를 한 번 더 눌러 정리해 주세요. 키가 그대로면 공간을 만든 뒤 다시 지워 주세요.")
    ROW_MISSING = "보관소에서 이 키를 찾지 못했어요. 지우고 다시 등록해 주세요."

    def drive_like_the_screen(self, state, starter):
        """쓰기 하나를 돌려 결과를 컨트롤러에 넘기고 **컨트롤러가 요청할 때만** 연결 정보를 다시 읽는다(화면 `_reload_after_keys` 가 하는 일 — `drive` 는 늘 다시 읽어서 이 요청 자체를 시험하지 못한다) → (종류, 값, 다시 읽었나)."""
        results = []
        status, job = starter(on_done=lambda result, _p: results.append(("ok", result)), on_error=lambda failure, _p: results.append(("err", failure)), on_cancel=lambda _p: results.append(("cancel", None)))
        self.assertEqual(status, "started")
        job.join(10)
        kind, value = results[0]
        controller = state.keys
        (controller.apply_write_ok if kind == "ok" else controller.apply_write_failed)(value)
        reloaded = controller.reload_wanted
        if reloaded:
            controller.reload_wanted, controller.reloading = False, True
            state.apply_connections(self.load())                                                   # 새 값을 받으면 `reloading` 이 꺼진다
        return kind, value, reloaded

    def two_keys(self):
        runner, state = self.env()
        controller = state.keys
        self.drive(state, lambda **cb: controller.start_add("ai_assist", "gemini", "가", box_of("ai_assist"), False, **cb))
        self.drive(state, lambda **cb: controller.start_add("ai_assist", "gemini", "나", box_of("ai_assist", OTHER), True, **cb))
        first, second = [item.ref for item in controller.info("ai_assist").entries]
        return runner, state, first, second

    @staticmethod
    def refuse_the_rename():
        """`connections.json` 로의 이름 바꾸기만 거절한다 — 그 앞의 키 저장소 삭제는 이미 끝났다(다른 파일은 진짜 `os.replace`)."""
        real = os.replace

        def replace(source, target, *args, **kwargs):
            if Path(target).name == "connections.json":
                raise PermissionError(errno.EACCES, "접근 거부(시험)")
            return real(source, target, *args, **kwargs)
        return mock.patch.object(os, "replace", replace)

    @staticmethod
    def disk_is_full():
        return mock.patch.object(cx, "_write_durably", side_effect=OSError(errno.ENOSPC, "디스크 가득(시험)"))

    @staticmethod
    def lock_is_unwritable():
        """키 저장소를 건드리기 전 단계(잠금)에서 같은 종류(`io`)로 실패 — 아무것도 안 바뀌는 쪽."""
        return mock.patch.object(cn.KeysLock, "acquire_waiting", side_effect=AppError("FILE_WRITE_FAILED", {"경로": "잠금"}))

    def check_a_delete_whose_file_write_fails_after_the_key_is_gone(self, inject, kind, sentence):
        runner, state, first, second = self.two_keys()
        controller = state.keys
        file_before = self.file_bytes()
        with inject():
            result, failure, reloaded = self.drive_like_the_screen(state, lambda **cb: controller.start_remove("ai_assist", first, **cb))
        self.assertEqual((result, failure.kind), ("err", kind))
        self.assertEqual((controller.notice, reloaded), (("error", sentence), True))
        self.assertFalse(controller.busy)
        # 실제로 일어난 일 — 키 저장소의 키는 이미 지워졌고 파일에는 항목이 그대로 남았다('바뀐 것은 없어요' 였다면 거짓이었다)
        self.assertEqual(self.store.list_refs(), ["ai_assist:" + second])
        self.assertEqual(self.file_bytes(), file_before)
        self.assertEqual(list(self.ctx.workspace.root.glob("*.tmp")), [])
        # 화면이 다시 읽은 값 — 그 행은 '키를 찾지 못했어요' 로 보이고 삭제는 눌린다
        self.assertEqual([(item.name, item.key_found) for item in controller.info("ai_assist").entries], [("가", False), ("나", True)])
        rows = controller.card_keys(controller.info("ai_assist"))["rows"]
        self.assertIn(self.ROW_MISSING, rows[0]["lines"])
        self.assertNotIn(self.ROW_MISSING, rows[1]["lines"])
        self.assertEqual([item["text"] for item in rows[0]["actions"] if item["key"] == "delete" and item["enabled"]], ["삭제"])
        # 한 번 더 지우면 정리된다(키 저장소 지우기는 멱등)
        result, done, reloaded = self.drive_like_the_screen(state, lambda **cb: controller.start_remove("ai_assist", first, **cb))
        self.assertEqual((result, done.kind, reloaded, controller.notice), ("ok", "removed", True, ("ok", "키를 지웠어요.")))
        self.assertEqual([item.name for item in controller.info("ai_assist").entries], ["나"])
        self.assertEqual(self.store.list_refs(), ["ai_assist:" + second])
        runner.join_all(5)
        self.assertEqual(leak.graph_hits((state, failure), NEEDLES, skip=(self.store, self)), [])
        self.assertEqual(leak.error_hits(failure, NEEDLES, skip=(self.provider, self.store, self.ctx)), [])
        self.assertEqual(leak.file_hits(self.ctx.workspace.root, NEEDLES), [])

    def test_a_delete_whose_file_replace_fails_after_the_key_is_gone_reads_again_and_a_second_delete_cleans_up(self):
        self.check_a_delete_whose_file_write_fails_after_the_key_is_gone(self.refuse_the_rename, "io", self.REMOVE_IO)

    def test_a_delete_that_meets_a_full_disk_after_the_key_is_gone_reads_again_and_a_second_delete_cleans_up(self):
        self.check_a_delete_whose_file_write_fails_after_the_key_is_gone(self.disk_is_full, "disk", self.REMOVE_DISK)

    def test_a_delete_that_fails_before_anything_was_removed_also_reads_again_and_the_same_sentence_is_still_true(self):
        """오류 종류(`io`)만으로는 '키가 이미 지워졌다' 와 '아무것도 안 바뀌었다' 를 구별할 수 없다 — 이쪽(잠금 단계의 실패)에서도 같은 문장이 참이다: 행은 그대로 있고 키도 그대로이며, 잠시 뒤 다시 지우면 지워진다."""
        runner, state, first, second = self.two_keys()
        controller = state.keys
        folder, refs = self.folder_state(), sorted(self.store.list_refs())
        with self.lock_is_unwritable():
            result, failure, reloaded = self.drive_like_the_screen(state, lambda **cb: controller.start_remove("ai_assist", first, **cb))
        self.assertEqual((result, failure.kind, reloaded, controller.notice), ("err", "io", True, ("error", self.REMOVE_IO)))
        self.assertEqual((self.folder_state(), sorted(self.store.list_refs())), (folder, refs), "아무것도 바뀌지 않았다")
        self.assertEqual([(item.name, item.key_found) for item in controller.info("ai_assist").entries], [("가", True), ("나", True)])
        for row in controller.card_keys(controller.info("ai_assist"))["rows"]:
            self.assertNotIn(self.ROW_MISSING, row["lines"])
        result, done, _reloaded = self.drive_like_the_screen(state, lambda **cb: controller.start_remove("ai_assist", first, **cb))
        self.assertEqual((result, done.kind), ("ok", "removed"))
        self.assertEqual(([item.name for item in controller.info("ai_assist").entries], self.store.list_refs()), (["나"], ["ai_assist:" + second]))
        runner.join_all(5)
        self.assertEqual(leak.graph_hits((state, failure), NEEDLES, skip=(self.store, self)), [])

    def test_reading_the_screen_never_calls_a_writer(self):
        runner, state = self.env()
        writes = []
        for name in ("add_key", "remove_key", "set_key_state", "rename_key", "move_key", "test_key"):
            setattr(self.provider, name, lambda *args, _name=name, **kwargs: writes.append(_name))
        for _ in range(3):
            state.apply_connections(self.load())
            state.settings_view()
            state.home_view()
        self.assertEqual(writes, [])


class SourceRulesTest(unittest.TestCase):
    WRITE_FUNCTIONS = {"add_entry", "remove_entry", "set_state", "rename_entry", "reorder", "test_entry", "mark_check", "mark_call_ok", "set_policy", "write_json"}
    FILE_WRITES = {"write_text", "write_bytes", "unlink", "mkdir", "rmdir", "rmtree", "copy2", "copyfile", "copytree", "touch", "makedirs", "chmod"}          # 이 이름은 어떤 값에 불러도 파일 쓰기다
    OS_WRITES = {"replace", "rename", "remove", "copy", "move"}                                                                                    # 문자열·dict 에도 있는 이름이라 `os`·`shutil` 에 부를 때만 센다

    def parse(self, path):
        return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    def test_screen_code_never_imports_the_service_or_the_key_store(self):
        for folder in ("core", "qt"):
            for path in sorted((UI / folder).glob("*.py")):
                for node in ast.walk(self.parse(path)):
                    if isinstance(node, (ast.Import, ast.ImportFrom)):
                        names = [alias.name for alias in node.names] if isinstance(node, ast.Import) else [("." * node.level) + (node.module or "")] + [alias.name for alias in node.names]
                        for name in names:
                            with self.subTest(file=path.name, name=name):
                                self.assertNotRegex(name, r"(^|\.)(service|keystore)(\.|$)", f"{path.name}: 화면 코드는 서비스·보관소를 직접 가져오지 않는다")

    def test_only_the_keys_adapter_calls_the_service_write_functions(self):
        found = {}
        for path in sorted(UI.rglob("*.py")):
            for node in ast.walk(self.parse(path)):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in self.WRITE_FUNCTIONS and "service" in ast.unparse(node.func.value).lower():
                    found.setdefault(path.name, set()).add(node.func.attr)
        # 병합 맞춤(M021): `seeds_adapter.py` 의 `set_state` 는 키 서비스가 아니라 Seed 서비스(`seed_manage`)의 같은 이름 함수다 — 그 어댑터만 부르는지는 Seed 시험이 지킨다. 기대 목록에 한 줄을 더할 뿐 느슨하게 하지 않는다
        self.assertEqual(found, {"keys_adapter.py": {"add_entry", "remove_entry", "set_state", "rename_entry", "reorder", "test_entry"}, "seeds_adapter.py": {"set_state"}})

    def test_screen_and_adapter_code_never_write_files_or_open_the_key_store_themselves(self):
        for folder in ("core", "qt"):
            for path in sorted((UI / folder).glob("*.py")):
                for node in ast.walk(self.parse(path)):
                    if isinstance(node, ast.Call):
                        name = node.func.attr if isinstance(node.func, ast.Attribute) else (node.func.id if isinstance(node.func, ast.Name) else "")
                        owner = ast.unparse(node.func.value) if isinstance(node.func, ast.Attribute) else ""
                        with self.subTest(file=path.name, line=node.lineno):
                            self.assertNotIn(name, self.FILE_WRITES, f"{path.name}:{node.lineno}")
                            self.assertFalse(name in self.OS_WRITES and owner in ("os", "shutil"), f"{path.name}:{node.lineno}")
                            self.assertFalse(isinstance(node.func, ast.Name) and node.func.id == "open", f"{path.name}:{node.lineno}")           # 내장 `open` — 위젯의 `.open()`(서랍) 같은 메서드는 아니다
        for path in (UI / "keys_adapter.py", UI / "adapters.py"):
            for node in ast.walk(self.parse(path)):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    self.assertNotIn(node.func.attr, self.FILE_WRITES, f"{path.name}:{node.lineno}")
                    self.assertFalse(node.func.attr in self.OS_WRITES and ast.unparse(node.func.value) in ("os", "shutil"), f"{path.name}:{node.lineno}")

    def test_the_read_adapter_never_asks_for_a_key_value_or_a_tail(self):
        tree = self.parse(UI / "adapters.py")
        cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "ServiceConnectionsProvider")
        calls = {ast.unparse(node.func) for node in ast.walk(cls) if isinstance(node, ast.Call)}
        for forbidden in ("connection_service.list_entries", "shape.tail_hint", "store.get", "keystore.get", "self._keystore.get", "fields.reveal", "entry.reveal"):
            self.assertNotIn(forbidden, calls)
        self.assertFalse({call for call in calls if call.endswith((".reveal", ".tail_hint", ".list_entries"))}, calls)
        self.assertIn("connection_service.secret_present", calls)

    def test_nothing_in_the_screen_modules_keeps_the_text_of_a_key_input(self):
        """키 칸의 `textChanged` 를 상태·컨트롤러에 잇거나 칸의 글을 `self.` 에 담는 코드가 없다(키 대화상자 소스를 훑는다 — 파일이 있을 때)."""
        path = UI / "qt" / "key_parts.py"
        if not path.exists():
            self.skipTest("키 부품 파일이 아직 없다")
        text = path.read_text(encoding="utf-8")
        self.assertNotRegex(text, r"textChanged\s*\.\s*connect\(\s*lambda\s+\w+\s*:")
        # 키 입력 칸(`secret_edits`)에는 글이 바뀔 때 부르는 신호를 잇지 않는다 — 글은 '다음'·'저장' 을 누르는 순간에만 읽는다. 눈에 보이는 별칭 칸은 키를 잘못 붙여 넣으면 바로 비워야 해서 `textEdited` 를 쓴다
        # (이 시험은 처음에 '파일 안에 textEdited 가 없다' 로 적었다 — 키 부품 파일이 생기기 전이라 거친 글자 검사였고, 별칭 칸을 허용하는 정확한 검사로 바꾼다. 키 칸에 이으면 여전히 실패한다)
        for node in ast.walk(ast.parse(text)):
            if isinstance(node, ast.Attribute) and node.attr in ("textChanged", "textEdited", "editingFinished", "returnPressed"):
                owner = ast.unparse(node.value)
                self.assertNotIn("secret", owner.lower(), f"{owner}.{node.attr}")
                self.assertIn(owner, ("self.alias_edit", "self.edit"), f"{owner}.{node.attr}")

    def test_the_new_service_text_has_no_english_secret_words(self):
        pattern = re.compile(r"(?i)\b(api[_ -]?key|secret|token|passw(?:or)?d|credential)s?\b")
        for name in ("connections.py", "context.py", "cli.py"):
            tree = self.parse(ROOT / "src" / "chanceblog_desktop" / "service" / name)
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    self.assertIsNone(pattern.search(node.value), f"{name}: {node.value[:40]}")


if __name__ == "__main__":
    unittest.main()
