"""키 항목 수 상한(운영자 정책 표)·별칭 바꾸기·쓰기 공유 위반 재시도 시험(P4f, 변경 등급 T2) — 실제 임시 폴더와 가짜 보관소로 돈다(네트워크·진짜 자격 증명 관리자 없음).

지키는 것:
  1) **상한 표는 시험이 값을 직접 적어 못박는다**(레지스트리 상수를 돌려 쓰지 않는다): 제공자마다 더할 때의 상한(NAVER API HUB 1·Unsplash 1·Pexels 1·Pixabay 1·검색광고 1·Gemini 3·Blogger 2)과 읽을 때의 천장(용도마다 3, API HUB 만 1),
     실제 표의 모든 제공자가 양수를 직접 적었다는 것(새 제공자가 조용히 옛 기본 3개를 물려받지 못한다), 둘째 키 약관 확인은 Blogger 만 빠진다.
  2) 더할 때: 상한을 넘기면 기존 오류 코드 `KEY_ENTRY_LIMIT` 로 거절하고(보관소·파일은 그대로) 새 오류 코드는 없다. 둘째 키 약관 확인은 같은 서비스(제공자)의 둘째 키에만이고 키를 하나만 두는 제공자는 약관을 묻기 전에 한도로 거절한다.
  3) **옛 파일·옛 항목을 지우거나 막지 않는다**(읽기는 그대로, 더하기만 거절): 상한을 넘는 옛 항목이 든 파일은 읽히고 목록·상태·순서·이름·지우기가 모두 되며, 천장을 넘는 파일은 지금처럼 깨진 파일이다.
  4) 별칭 바꾸기(`rename_entry`): 이름 칸만 바뀌고 값·상태·순서는 그대로, 같은 이름·키 모양 이름·보관된 값이 든 이름은 거절(문구에 값이 없다), 보관소를 못 열면 바꾸지 않는다.
  5) `write_json` 의 이름 바꾸기 재시도: 윈도 공유 위반(`winerror` 5·32)이면 합쳐 0.45초 안에 여섯 번 시도하고 그래도 안 되면 기존 오류를 그대로 내며, 다른 오류는 다시 하지 않는다 — 옛 파일은 안 바뀌고 임시 파일은 정리된다.
  6) 명령줄 `keys add` 의 선검사가 같은 규칙(`check_room`)을 쓴다 — 키를 하나만 두는 제공자는 키를 읽기 전에 거절한다.
가짜 키는 실행할 때 조각을 이어 붙여 만든다(저장소에는 키 문자열이 없다).
"""
import errno
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import service_support as ss  # noqa: E402

from chanceblog_desktop.errors import CATALOG, AppError  # noqa: E402
from chanceblog_desktop.security import keystore as ks  # noqa: E402
from chanceblog_desktop.security import shape  # noqa: E402
from chanceblog_desktop.service import cli  # noqa: E402
from chanceblog_desktop.service import connections as c  # noqa: E402
from chanceblog_desktop.service import context  # noqa: E402

# 운영자 정책 표(2026-11-06) — 값을 이 시험이 직접 적는다. 바꾸려면 새 결정과 함께 여기도 고친다.
ADD_CAPS = {("naver_apihub", ""): 1, ("naver_searchad", ""): 1, ("image_provider", "unsplash"): 1, ("image_provider", "pexels"): 1, ("image_provider", "pixabay"): 1, ("ai_assist", "gemini"): 3, ("blogger", ""): 2}
READ_CEILINGS = {"naver_apihub": 1, "naver_searchad": 3, "image_provider": 3, "ai_assist": 3, "blogger": 3, "github_repo": 3, "naver_openapi": 3}
ID1, ID2, ID3, ID4 = "abcdef01" * 4, "abcdef02" * 4, "abcdef03" * 4, "abcdef04" * 4


def piece(*parts):
    """실행 중 조각을 이어 붙인 가짜 값 — 저장소의 `.py` 에는 이어진 모양이 없다."""
    return "".join(parts)


def fake_fields(purpose, seed="a"):
    """용도의 모든 칸에 넣을 가짜 값(칸마다·seed 마다 다르고 최소 길이를 넘는다)."""
    found = {}
    for index, item in enumerate(c.PURPOSES[purpose].fields):
        body = piece(seed, str(index), "Zk3x9Qm7") * 40
        found[item.name] = body[: item.min_len + 4]
    return found


def raw_entry(purpose, entry_id, *, provider="", name="기본", order=1, state="active"):
    """옛 프로그램이 `connections.json` 에 적었을 항목 하나(칸 이름은 `Entry.to_dict` 와 같다)."""
    return {"entry_id": entry_id, "purpose": purpose, "provider": provider, "name": name, "project": "", "order": order, "state": state, "created_at": "2026-10-30T01:00:00Z",
            "checked_at": "", "last_ok_at": "", "check_result": "", "bucket": "p-" + str(order), "terms_ack_at": ""}


def write_file(ctx, entries):
    path = ctx.workspace.connections_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema": 1, "entries": entries, "policies": {}}, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path.read_bytes()


def surfaces(error):
    shown = error.rendered()
    return [str(error), error.log_line(), shown.message, shown.action, shown.retry_text, str(error.detail), repr(error), repr(error.slots), " ".join(str(v) for v in error.slots.values()), repr(error.args)]


class FakeStdin(io.StringIO):
    def __init__(self, text="", tty=False):
        super().__init__(text)
        self.tty = tty
        self.reads = 0

    def isatty(self):
        return self.tty

    def read(self, size=-1):
        self.reads += 1
        return super().read(size)


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.ctx = ss.make_ctx(self.tmp, clock=ss.Clock())
        self.store = self.ctx.keystore

    def file_bytes(self):
        path = self.ctx.workspace.connections_path
        return path.read_bytes() if path.exists() else None

    def add(self, purpose, name="기본", seed="a", **kwargs):
        return c.add_entry(self.ctx, purpose, name=name, fields=fake_fields(purpose, seed), **kwargs)

    def refused(self, purpose, **kwargs):
        """같은 일이 `KEY_ENTRY_LIMIT` 로 거절되고 보관소·파일이 그대로다 → 오류."""
        refs, before = self.store.list_refs(), self.file_bytes()
        error = ss.code_of(c.add_entry, self.ctx, purpose, **kwargs)
        self.assertEqual(error.code, "KEY_ENTRY_LIMIT", f"{error.slots} {error.detail}")
        self.assertEqual(self.store.list_refs(), refs)
        self.assertEqual(self.file_bytes(), before)
        return error

    def run_keys(self, *argv, stdin=""):
        out, err = io.StringIO(), io.StringIO()
        source = FakeStdin(stdin)
        code = cli.main(["keys", *argv], out=out, err=err, ctx=self.ctx, stdin=source)
        return code, out.getvalue(), err.getvalue(), source


# ---- 1) 상한 표 ---------------------------------------------------------------------------------------------------------------------
class TableTest(unittest.TestCase):
    def test_every_provider_has_the_cap_the_operator_policy_table_says(self):
        found = {(key, provider.key): c.PURPOSES[key].entry_cap(provider.key) for key, spec in c.PURPOSES.items() if spec.takes_keys and not spec.legacy_to for provider in spec.providers}
        self.assertEqual(found, ADD_CAPS)

    def test_the_read_ceilings_of_a_file_are_unchanged_so_old_files_stay_readable(self):
        self.assertEqual({key: spec.max_entries for key, spec in c.PURPOSES.items()}, READ_CEILINGS)
        self.assertEqual(c.MAX_ENTRIES_PER_PURPOSE, 3)

    def test_every_real_provider_of_a_key_taking_purpose_wrote_its_own_positive_cap(self):
        """새 제공자가 옛 기본(용도 천장 3)을 조용히 물려받지 못한다 — 상한을 직접 적게 한다."""
        for key, spec in c.PURPOSES.items():
            if not spec.takes_keys or spec.legacy_to:
                continue
            for provider in spec.providers:
                with self.subTest(purpose=key, provider=provider.key):
                    self.assertGreater(provider.max_entries, 0)
                    self.assertLessEqual(provider.max_entries, spec.max_entries)

    def test_a_provider_without_a_cap_follows_the_purpose_ceiling_like_before(self):
        """표에 없는 시험용 제공자(`max_entries` 0)는 용도의 천장을 따른다 — 옛 동작 그대로(`ss.generic_registry()` 가 쓴다)."""
        spec = ss.generic_registry()["naver_openapi"]
        self.assertEqual((spec.providers[0].max_entries, spec.entry_cap(""), spec.entry_cap("모르는 제공자")), (0, 3, 3))

    def test_only_blogger_skips_the_second_key_terms_check(self):
        flags = {(key, provider.key): provider.second_key_needs_terms for key, spec in c.PURPOSES.items() for provider in spec.providers}
        self.assertEqual({pair for pair, needs in flags.items() if not needs}, {("blogger", "")})

    def test_the_limit_uses_the_existing_error_code_and_no_new_key_error_code_exists(self):
        self.assertIn("KEY_ENTRY_LIMIT", CATALOG)
        self.assertEqual(sorted(code for code in CATALOG if code.startswith("KEY_")), ["KEY_AUTH_FAILED", "KEY_DUPLICATE", "KEY_ENTRY_LIMIT", "KEY_FAILOVER_TERMS_REQUIRED", "KEY_INVALID_SHAPE", "KEY_STORE_UNAVAILABLE", "KEY_TOO_LONG"])


# ---- 2) 더할 때 ---------------------------------------------------------------------------------------------------------------------
class AddTest(Base):
    def test_unsplash_takes_one_key_and_the_second_is_refused_even_with_the_terms_and_nothing_changes(self):
        self.add("image_provider", provider="unsplash")
        spec = c.PURPOSES["image_provider"]
        for kwargs in ({}, {"terms_ack": True}, {"terms_ack": True, "state": "standby"}, {"terms_ack": True, "project": "다른 앱"}):
            with self.subTest(kwargs=kwargs):
                error = self.refused("image_provider", name="둘째", fields=fake_fields("image_provider", "b"), provider="unsplash", **kwargs)
                self.assertEqual((error.slots, error.detail), ({"용도": spec.label, "개수": "1"}, c.PROVIDER_LIMIT_DETAIL))
                self.assertIn("「1」개까지만", error.rendered().message)
                for phrase in ("하나만", "돌려 쓰지 않습니다", "keys remove"):
                    self.assertIn(phrase, error.detail)

    def test_each_image_provider_takes_its_own_first_key_without_a_terms_question_but_not_a_second(self):
        first = self.add("image_provider", "언스플래시", "a", provider="unsplash")
        second = self.add("image_provider", "펙셀스", "b", provider="pexels")
        third = self.add("image_provider", "픽사베이", "c", provider="pixabay")
        self.assertEqual([entry.notes for entry in (first, second, third)], [(), (), ()])
        self.assertEqual([entry.entry.terms_ack_at for entry in (first, second, third)], ["", "", ""])
        self.assertEqual([entry.entry.order for entry in (first, second, third)], [1, 2, 3])
        for provider in ("unsplash", "pexels", "pixabay"):
            with self.subTest(provider=provider):
                self.refused("image_provider", name="더", fields=fake_fields("image_provider", "d"), provider=provider, terms_ack=True)
        self.assertEqual(len(c.load(self.ctx).of_purpose("image_provider")), 3)

    def test_the_first_provider_is_the_default_so_an_unnamed_provider_counts_as_unsplash(self):
        self.add("image_provider")
        self.refused("image_provider", name="둘째", fields=fake_fields("image_provider", "b"), terms_ack=True)

    def test_other_services_take_one_key_too(self):
        self.add("naver_searchad")
        error = self.refused("naver_searchad", name="둘째", fields=fake_fields("naver_searchad", "b"), terms_ack=True)
        self.assertEqual((error.slots, error.detail), ({"용도": c.PURPOSES["naver_searchad"].label, "개수": "1"}, c.PROVIDER_LIMIT_DETAIL))

    def test_naver_api_hub_keeps_its_one_key_and_its_own_detail_text(self):
        self.add("naver_apihub")
        error = self.refused("naver_apihub", name="둘째", fields=fake_fields("naver_apihub", "b"), terms_ack=True)
        self.assertEqual((error.slots, error.detail), ({"용도": c.PURPOSES["naver_apihub"].label, "개수": "1"}, c.ENTRY_LIMIT_DETAIL))

    def test_an_ai_provider_takes_three_keys_with_the_terms_from_the_second_and_refuses_the_fourth(self):
        spec = c.PURPOSES["ai_assist"]
        first = self.add("ai_assist", "가", "a", provider="gemini")
        error = ss.code_of(c.add_entry, self.ctx, "ai_assist", name="나", fields=fake_fields("ai_assist", "b"))
        self.assertEqual(error.code, "KEY_FAILOVER_TERMS_REQUIRED")
        second = self.add("ai_assist", "나", "b", terms_ack=True)
        third = self.add("ai_assist", "다", "c", terms_ack=True)
        self.assertEqual([entry.entry.terms_ack_at != "" for entry in (first, second, third)], [False, True, True])
        self.assertEqual([c.TERMS_NOTICE in entry.notes for entry in (first, second, third)], [False, True, True])
        error = self.refused("ai_assist", name="라", fields=fake_fields("ai_assist", "d"), terms_ack=True)
        self.assertEqual((error.slots, error.detail), ({"용도": spec.label, "개수": "3"}, ""))
        self.assertIn("「3」개까지만", error.rendered().message)

    def test_blogger_takes_one_connection_per_channel_so_two_without_a_terms_question_and_no_third(self):
        first = self.add("blogger", "한글", "a")
        second = self.add("blogger", "영문", "b")                                  # 약관 확인 없이 — 둘째가 같은 서비스의 한도를 나누는 키가 아니라 다른 채널의 연결이다
        self.assertEqual((second.notes, second.entry.terms_ack_at, first.entry.order, second.entry.order), ((), "", 1, 2))
        error = self.refused("blogger", name="셋째", fields=fake_fields("blogger", "c"), terms_ack=True)
        self.assertEqual((error.slots, error.detail), ({"용도": c.PURPOSES["blogger"].label, "개수": "2"}, ""))

    def test_a_removed_key_makes_room_again_and_the_replacement_is_the_way_to_change_a_key(self):
        entry = self.add("image_provider", provider="unsplash").entry
        c.remove_entry(self.ctx, entry.entry_id, confirmed=True, keystore=self.store)
        again = self.add("image_provider", "새 키", "b", provider="unsplash")
        self.assertEqual([item.name for item in c.load(self.ctx).of_purpose("image_provider")], ["새 키"])
        self.assertEqual(self.store.list_refs(), [again.entry.ref])

    def test_check_room_is_one_rule_for_every_caller(self):
        spec = c.PURPOSES["image_provider"]
        unsplash = spec.provider("unsplash")
        pexels = spec.provider("pexels")
        mine = (c.Entry(ID1, "image_provider", "unsplash", "가", "", 1, "active", "2026-10-30T01:00:00Z", "", "", "", "p-1", ""),)
        self.assertIsNone(c.check_room(spec, unsplash, ()))
        self.assertIsNone(c.check_room(spec, pexels, mine))                     # 다른 제공자의 첫 키는 자리가 있다
        self.assertEqual(ss.code_of(c.check_room, spec, unsplash, mine).slots, {"용도": spec.label, "개수": "1"})
        self.assertEqual(c.check_room.__module__, "chanceblog_desktop.service.connections")

    def test_the_ceiling_of_a_purpose_still_refuses_when_every_provider_has_room(self):
        """용도의 읽을 때 천장(3)에 닿았으면 제공자 상한이 남아 있어도 거절한다(천장이 더 낮을 때의 안전장치)."""
        registry = dict(c.PURPOSES)
        spec = registry["ai_assist"]
        registry["ai_assist"] = type(spec)(**{**spec.__dict__, "max_entries": 2})
        for seed in "ab":
            c.add_entry(self.ctx, "ai_assist", name=f"키{seed}", fields=fake_fields("ai_assist", seed), terms_ack=True, registry=registry)
        error = ss.code_of(c.add_entry, self.ctx, "ai_assist", name="키c", fields=fake_fields("ai_assist", "c"), terms_ack=True, registry=registry)
        self.assertEqual((error.code, error.slots["개수"]), ("KEY_ENTRY_LIMIT", "2"))


# ---- 3) 옛 파일·옛 항목 ----------------------------------------------------------------------------------------------------------
class OldFileTest(Base):
    def old_world(self):
        """상한이 낮아지기 전의 프로그램이 만들었을 상태 — Unsplash 키 셋이 든 파일과 보관소의 값."""
        entries = [raw_entry("image_provider", entry_id, provider="unsplash", name=name, order=index) for index, (entry_id, name) in enumerate(((ID1, "옛 기본"), (ID2, "옛 예비"), (ID3, "옛 셋째")), start=1)]
        for entry, seed in zip(entries, "abc", strict=True):
            self.store.put("image_provider:" + entry["entry_id"], fake_fields("image_provider", seed))
        return write_file(self.ctx, entries)

    def test_a_file_with_more_entries_than_the_new_cap_is_read_listed_and_untouched(self):
        raw = self.old_world()
        data = c.load(self.ctx)
        self.assertEqual([item.name for item in data.of_purpose("image_provider")], ["옛 기본", "옛 예비", "옛 셋째"])
        views = c.list_entries(self.ctx, keystore=self.store)
        self.assertEqual(len(views), 3)
        self.assertEqual(self.file_bytes(), raw, "읽기는 파일을 바꾸지 않는다")
        self.assertEqual(len(self.store.list_refs()), 3)
        self.assertEqual(c.purpose_status(self.ctx, data, "image_provider", keystore=self.store), c.NEEDS_CHECK)

    def test_every_change_to_an_old_entry_still_works_and_only_adding_is_refused(self):
        self.old_world()
        c.set_state(self.ctx, ID2, "standby")
        c.reorder(self.ctx, "image_provider", [ID3, ID1, ID2])
        renamed, before = c.rename_entry(self.ctx, ID1, "새 이름", keystore=self.store)
        self.assertEqual((renamed.name, before), ("새 이름", "옛 기본"))
        names = [(item.name, item.state) for item in c.load(self.ctx).of_purpose("image_provider")]
        self.assertEqual(names, [("옛 셋째", "active"), ("새 이름", "active"), ("옛 예비", "standby")])
        self.refused("image_provider", name="넷째", fields=fake_fields("image_provider", "d"), provider="unsplash", terms_ack=True)
        c.remove_entry(self.ctx, ID3, confirmed=True, keystore=self.store)
        self.assertEqual(len(c.load(self.ctx).of_purpose("image_provider")), 2)
        self.refused("image_provider", name="다시", fields=fake_fields("image_provider", "e"), provider="unsplash", terms_ack=True)       # 둘이 남아 있어도 더하기는 거절 — 지우기는 막지 않는다
        c.remove_entry(self.ctx, ID1, confirmed=True, keystore=self.store)
        c.remove_entry(self.ctx, ID2, confirmed=True, keystore=self.store)
        self.assertEqual(self.store.list_refs(), [])
        self.add("image_provider", provider="unsplash")                      # 다 지우면 다시 더할 수 있다

    def test_old_blogger_entries_up_to_the_old_ceiling_are_read_and_a_fourth_entry_is_still_a_broken_file(self):
        entries = [raw_entry("blogger", entry_id, name=name, order=index) for index, (entry_id, name) in enumerate(((ID1, "가"), (ID2, "나"), (ID3, "다")), start=1)]
        for entry in entries:
            entry["bucket"] = "id-" + shape.short_digest("blogid" + entry["entry_id"][:6])
        write_file(self.ctx, entries)
        self.assertEqual(len(c.load(self.ctx).of_purpose("blogger")), 3)
        self.refused("blogger", name="넷째", fields=fake_fields("blogger", "d"), terms_ack=True)
        write_file(self.ctx, entries + [{**entries[0], "entry_id": ID4, "name": "넷째"}])
        self.assertEqual(ss.code_of(c.load, self.ctx).code, "CONNECTIONS_FILE_INVALID")

    def test_four_unsplash_entries_are_still_a_broken_file_and_two_hub_entries_too(self):
        entries = [raw_entry("image_provider", entry_id, provider="unsplash", name=f"옛{index}", order=index) for index, entry_id in enumerate((ID1, ID2, ID3, ID4), start=1)]
        write_file(self.ctx, entries)
        error = ss.code_of(c.load, self.ctx)
        self.assertEqual((error.code, error.detail), ("CONNECTIONS_FILE_INVALID", "한 용도의 항목이 3개를 넘는다"))
        write_file(self.ctx, [raw_entry("naver_apihub", ID1), raw_entry("naver_apihub", ID2, name="둘째", order=2)])
        error = ss.code_of(c.load, self.ctx)
        self.assertEqual((error.code, error.detail), ("CONNECTIONS_FILE_INVALID", "한 용도의 항목이 1개를 넘는다"))

    def test_the_command_line_lists_and_removes_old_entries_with_the_same_output_as_before(self):
        self.old_world()
        code, out, err, _ = self.run_keys("list")
        self.assertEqual((code, err), (0, ""))
        self.assertIn("키 항목 3개", out)
        self.assertEqual(self.run_keys("remove", ID3[:8], "--yes")[0], 0)
        self.assertEqual(len(c.load(self.ctx).of_purpose("image_provider")), 2)


# ---- 4) 별칭 바꾸기 -----------------------------------------------------------------------------------------------------------------
class RenameTest(Base):
    def setUp(self):
        super().setUp()
        self.first = self.add("ai_assist", "가", "a", new_id=lambda: ID1).entry
        self.second = self.add("ai_assist", "나", "b", terms_ack=True, new_id=lambda: ID2).entry

    def test_only_the_name_changes_and_the_previous_good_file_is_kept_as_the_backup(self):
        before = self.file_bytes()
        entry, old = c.rename_entry(self.ctx, ID1, "새 별칭", keystore=self.store)
        self.assertEqual((entry.name, old), ("새 별칭", "가"))
        after = {item.entry_id: item for item in c.load(self.ctx).entries}
        self.assertEqual({key: value for key, value in after[ID1].to_dict().items() if key != "name"}, {key: value for key, value in self.first.to_dict().items() if key != "name"})
        self.assertEqual(after[ID2], self.second)
        self.assertEqual((self.ctx.workspace.connections_path.with_name("connections.json.bak")).read_bytes(), before)
        self.assertEqual(self.store.get("ai_assist:" + ID1).to_dict(), fake_fields("ai_assist", "a"))
        self.assertEqual(sorted(self.store.list_refs()), ["ai_assist:" + ID1, "ai_assist:" + ID2])

    def test_the_same_name_is_nothing_changed_and_writes_nothing(self):
        before = self.file_bytes()
        with mock.patch.object(c, "write_json", side_effect=AssertionError("쓰면 안 된다")):
            entry, old = c.rename_entry(self.ctx, ID1, "가", keystore=self.store)
        self.assertEqual((entry.name, old), ("가", "가"))
        self.assertEqual(self.file_bytes(), before)

    def test_another_entrys_name_is_refused_but_the_same_name_in_another_purpose_is_fine(self):
        before = self.file_bytes()
        error = ss.code_of(c.rename_entry, self.ctx, ID1, "나", keystore=self.store)
        self.assertEqual(error.code, "KEY_DUPLICATE")
        self.assertEqual(self.file_bytes(), before)
        image = self.add("image_provider", "다른 용도", "c", provider="unsplash").entry
        self.assertEqual(c.rename_entry(self.ctx, image.entry_id, "나", keystore=self.store)[0].name, "나")

    def test_a_bad_name_is_refused_with_the_shape_code_and_the_file_stays(self):
        before = self.file_bytes()
        long_name = "가" * (c.MAX_NAME_CHARS + 1)
        keyish = piece("g", "hp_", "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8")
        for name in ("", " 앞공백", "두  칸", long_name, "줄" + chr(10) + "바꿈", keyish, "제로" + chr(0x200B) + "폭"):
            with self.subTest(name=name[:12]):
                error = ss.code_of(c.rename_entry, self.ctx, ID1, name, keystore=self.store)
                self.assertEqual(error.code, "KEY_INVALID_SHAPE")
                self.assertNotIn(keyish, " ".join(surfaces(error)))
                self.assertEqual(self.file_bytes(), before)

    def test_a_stored_value_pasted_into_the_name_is_refused_without_repeating_it(self):
        before = self.file_bytes()
        value = self.store.get("ai_assist:" + ID1).reveal("key")
        for name in (value, "앞" + value + "뒤"):                    # 키 모양이 아니어도(스무 글자) 보관된 값이 이름에 통째로 든 것은 거절한다
            with self.subTest(name=name[:8]):
                error = ss.code_of(c.rename_entry, self.ctx, ID1, name, keystore=self.store)
                self.assertEqual(error.code, "KEY_INVALID_SHAPE")
                for text in surfaces(error):
                    for probe in (value, value[:8], value[-6:]):
                        self.assertNotIn(probe, text)
                self.assertEqual(self.file_bytes(), before)

    def test_without_a_readable_keystore_nothing_is_renamed(self):
        class Broken(ks.MemoryStore):
            def _read(self, ref):
                raise AppError("KEY_STORE_UNAVAILABLE", detail="시험용 실패")

        before = self.file_bytes()
        error = ss.code_of(c.rename_entry, self.ctx, ID1, "새 이름", keystore=Broken())
        self.assertEqual(error.code, "KEY_STORE_UNAVAILABLE")
        self.assertEqual(self.file_bytes(), before)

    def test_a_value_that_is_gone_from_the_store_does_not_stop_the_rename(self):
        self.store.delete("ai_assist:" + ID1)
        self.assertEqual(c.rename_entry(self.ctx, ID1, "값 없는 항목", keystore=self.store)[0].name, "값 없는 항목")

    def test_unknown_entries_and_a_busy_lock_change_nothing(self):
        before = self.file_bytes()
        self.assertEqual(ss.code_of(c.rename_entry, self.ctx, "ab" * 16, "이름", keystore=self.store).code, "CONNECTION_NOT_FOUND")
        with mock.patch.object(c.KeysLock, "acquire_waiting", side_effect=AppError("KEYS_BUSY", {"작업": "x"})):
            self.assertEqual(ss.code_of(c.rename_entry, self.ctx, ID1, "이름", keystore=self.store).code, "KEYS_BUSY")
        self.assertEqual(self.file_bytes(), before)

    def test_a_broken_file_is_not_written_over(self):
        self.ctx.workspace.connections_path.write_text("{ 깨진", encoding="utf-8")
        before = self.file_bytes()
        self.assertEqual(ss.code_of(c.rename_entry, self.ctx, ID1, "이름", keystore=self.store).code, "CONNECTIONS_FILE_INVALID")
        self.assertEqual(self.file_bytes(), before)

    def test_the_rename_is_the_only_new_service_writer_and_goes_through_save(self):
        """새 쓰기 길이 없다 — 별칭 바꾸기도 기존 `save`(= `write_json`) 한 곳으로만 쓴다."""
        with mock.patch.object(c, "write_json", wraps=c.write_json) as writer:
            c.rename_entry(self.ctx, ID1, "저장 한 곳", keystore=self.store)
        self.assertEqual([call.args[0].name for call in writer.call_args_list], ["connections.json.bak", "connections.json"])


# ---- 5) 쓰기 공유 위반 재시도 --------------------------------------------------------------------------------------------------------
def sharing_error(number=32):
    error = PermissionError(errno.EACCES, "다른 프로세스가 파일을 쓰고 있어요")
    error.winerror = number                                   # 윈도가 아닌 곳에서도 같은 모양으로(인스턴스 칸)
    return error


class RetryTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "data.json"
        context.write_json(self.path, {"값": "옛 내용"})
        self.old = self.path.read_bytes()
        self.waits = []
        patcher = mock.patch.object(context, "_sleep", side_effect=self.waits.append)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.real_replace = context.os.replace

    def failing(self, errors, calls):
        """앞의 `errors`(오류 목록)를 차례로 내고 그 뒤에는 진짜 이름 바꾸기를 한다."""
        queue = list(errors)

        def fake(source, target):
            calls.append((source, target))
            if queue:
                raise queue.pop(0)
            return self.real_replace(source, target)
        return fake

    def leftovers(self):
        return sorted(item.name for item in self.path.parent.iterdir() if item.name != "data.json")

    def test_the_schedule_is_six_attempts_in_under_half_a_second(self):
        self.assertEqual(context.REPLACE_RETRY_WAITS, (0.03, 0.06, 0.09, 0.12, 0.15))
        self.assertLessEqual(sum(context.REPLACE_RETRY_WAITS), 0.5)
        self.assertEqual(context.SHARING_VIOLATIONS, (5, 32))

    def test_a_few_sharing_violations_then_success_writes_the_new_content_once(self):
        for number in (32, 5):
            with self.subTest(winerror=number):
                self.waits.clear()
                calls = []
                with mock.patch.object(context.os, "replace", side_effect=self.failing([sharing_error(number)] * 3, calls)):
                    context.write_json(self.path, {"값": f"새 내용 {number}"})
                self.assertEqual(len(calls), 4)
                self.assertEqual(self.waits, [0.03, 0.06, 0.09])
                self.assertEqual(json.loads(self.path.read_text(encoding="utf-8")), {"값": f"새 내용 {number}"})
                self.assertEqual(self.leftovers(), [])

    def test_a_violation_that_never_goes_away_gives_the_old_error_after_six_attempts_and_cleans_up(self):
        calls = []
        with mock.patch.object(context.os, "replace", side_effect=self.failing([sharing_error()] * 10, calls)):
            error = ss.code_of(context.write_json, self.path, {"값": "안 써진다"})
        self.assertEqual(error.code, "FILE_WRITE_FAILED")
        self.assertEqual(len(calls), 6)
        self.assertEqual(self.waits, [0.03, 0.06, 0.09, 0.12, 0.15])
        self.assertLessEqual(sum(self.waits), 0.5)
        self.assertEqual(self.path.read_bytes(), self.old, "옛 파일은 안 바뀐다")
        self.assertEqual(self.leftovers(), [], "임시 파일은 정리된다")

    def test_the_last_attempt_may_still_succeed(self):
        calls = []
        with mock.patch.object(context.os, "replace", side_effect=self.failing([sharing_error()] * 5, calls)):
            context.write_json(self.path, {"값": "여섯 번째에 성공"})
        self.assertEqual((len(calls), len(self.waits)), (6, 5))
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8")), {"값": "여섯 번째에 성공"})

    def test_other_errors_are_not_retried(self):
        permission_other = PermissionError(errno.EACCES, "권한 없음")
        permission_other.winerror = 87                          # 다른 윈도 오류 번호
        cases = {"공유 위반이 아닌 접근 거부(번호 없음)": (PermissionError(errno.EACCES, "권한 없음"), "FILE_WRITE_FAILED"), "다른 윈도 오류 번호": (permission_other, "FILE_WRITE_FAILED"),
                 "디스크 가득": (OSError(errno.ENOSPC, "가득"), "DISK_FULL"), "다른 입출력 오류": (OSError(errno.EIO, "입출력"), "FILE_WRITE_FAILED")}
        for label, (problem, code) in cases.items():
            with self.subTest(label):
                self.waits.clear()
                calls = []
                with mock.patch.object(context.os, "replace", side_effect=self.failing([problem], calls)):
                    error = ss.code_of(context.write_json, self.path, {"값": "안 써진다"})
                self.assertEqual((error.code, len(calls), self.waits), (code, 1, []))
                self.assertEqual(self.path.read_bytes(), self.old)
                self.assertEqual(self.leftovers(), [])

    def test_the_retry_wraps_only_the_rename_and_a_writing_error_is_not_retried(self):
        calls = []
        with mock.patch.object(context, "_write_durably", side_effect=sharing_error()), mock.patch.object(context.os, "replace", side_effect=self.failing([], calls)):
            error = ss.code_of(context.write_json, self.path, {"값": "x"})
        self.assertEqual((error.code, calls, self.waits), ("FILE_WRITE_FAILED", [], []))

    def test_a_success_the_first_time_never_sleeps(self):
        context.write_json(self.path, {"값": "바로 성공"})
        self.assertEqual(self.waits, [])


# ---- 6) 명령줄 ----------------------------------------------------------------------------------------------------------------------
class CliTest(Base):
    def test_a_one_key_provider_is_refused_before_the_key_is_read_or_the_terms_are_asked(self):
        self.add("image_provider", provider="unsplash")
        refs, before = self.store.list_refs(), self.file_bytes()
        for extra in ((), ("--i-understand-terms",), ("--provider", "unsplash")):
            with self.subTest(extra=extra):
                code, out, err, source = self.run_keys("add", "image_provider", "--name", "둘째", "--stdin", *extra, stdin=json.dumps(fake_fields("image_provider", "b")))
                self.assertEqual((code, out, source.reads), (1, "", 0))
                self.assertIn("코드: KEY_ENTRY_LIMIT", err)
                self.assertNotIn("KEY_FAILOVER_TERMS_REQUIRED", err)
        self.assertEqual((self.store.list_refs(), self.file_bytes()), (refs, before))

    def test_another_provider_of_the_same_purpose_has_its_own_room_and_asks_no_terms(self):
        self.add("image_provider", provider="unsplash")
        code, out, err, source = self.run_keys("add", "image_provider", "--name", "펙셀스", "--provider", "pexels", "--stdin", stdin=json.dumps(fake_fields("image_provider", "b")))
        self.assertEqual((code, err), (0, ""), out)
        self.assertEqual(source.reads, 1)

    def test_blogger_asks_no_terms_for_the_second_channel_and_refuses_a_third_after_reading_the_key(self):
        for name, seed in (("한글", "a"), ("영문", "b")):
            code, out, err, _ = self.run_keys("add", "blogger", "--name", name, "--stdin", stdin=json.dumps(fake_fields("blogger", seed)))
            self.assertEqual((code, err), (0, ""), out)
        code, out, err, source = self.run_keys("add", "blogger", "--name", "셋째", "--stdin", "--i-understand-terms", stdin=json.dumps(fake_fields("blogger", "c")))
        self.assertEqual((code, out), (1, ""))
        self.assertIn("코드: KEY_ENTRY_LIMIT", err)


if __name__ == "__main__":
    unittest.main()
