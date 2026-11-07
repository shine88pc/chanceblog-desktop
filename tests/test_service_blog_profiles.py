"""블로그 프로필 쓰기(`service/blog_profiles.py` — P4b, 변경 등급 T2) 시험. **전부 임시 폴더**(이 PC 의 실제 데이터 폴더·설정 파일에는 쓰지 않는다). 네트워크·실제 시계·키 보관소 없이 돈다.

지키는 것:
  1) 읽기: 파일이 없으면 기본 프로필 다섯 개(파일도 폴더도 만들지 않는다)·0바이트도 '아직 없음'·틀린 파일은 고치거나 덮어쓰지 않고 멈춘다·판 1 파일도 읽는다·글칸의 키 모양은 읽지 않는다.
  2) 저장: 한 슬롯의 폼 칸만 바뀌고 엔진 칸·다른 슬롯·화면이 모르는 칸은 그대로·바뀐 것이 없으면 잠금도 파일도 만들지 않는다·틀린 값은 칸마다 알리고 아무것도 쓰지 않는다·키 모양 글은 쓰기 전에 거른다.
  3) 복제·삭제: 비어 있는 같은 종류 슬롯으로만 복사(덮어쓰기 금지)·삭제는 슬롯을 비울 뿐 슬롯이 사라지지 않고 확인 표시(진짜 `True`)가 없으면 읽지도 않는다.
  4) **쓰기 안전**(실패 주입 — 진짜 `os` 호출에 끼워 넣는다): 백업 쓰는 중·본 파일 임시 파일 쓰는 중·디스크에 내려보내기·이름 바꾸기 직전·이름 바꾼 직후 읽기 검증 실패·백업 실패·읽기 전용·디스크 가득·낡은 판·다른 창이 쥔 잠금에서
     **기존 값이 한 바이트도 안 바뀌거나(되돌림) 직전 내용으로 돌아가고**, 임시 파일·잠금 파일이 남지 않으며, 같은 일을 다시 하면 된다.
  5) 동시 저장: 같은 읽기에서 출발한 두 저장 중 하나만 저장되고 다른 하나는 낡은 판(`STORE_CONFLICT`)이나 잠금(`TOPIC_STORE_LOCKED`)으로 물러난다(잃어버린 갱신이 없다) · 진짜 프로세스 둘이 서로 다른 슬롯을 번갈아 저장해도 마지막 값이 모두 남는다.
  6) 쓰기가 닿는 곳은 `channel_profiles.json`·`.bak`·`.v1.bak`·잠금뿐이다(다른 파일은 바이트까지 그대로) · 소스에 낮은 수준 쓰기 호출이 없고 실제 블로그 이름·아이디가 저장소 어디에도 없다.
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

from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.service import blog_profiles as bp  # noqa: E402
from chanceblog_desktop.service import topic_files as tf  # noqa: E402
from chanceblog_desktop.topics import channels, layout, wording  # noqa: E402

ROOT = ss.ROOT
KEY_SHAPED = "AK" + "IA" + "ABCDEFGHIJKLMNOP"        # 키 모양의 가짜 값 — 20자라 표시 이름(30자)에도 들어간다(조각으로 나눠 적어 저장소에 키 문자열이 없다)
REAL = {name: getattr(os, name) for name in ("open", "write", "fsync", "close", "replace")}


def code_of(call, *args, **kwargs):
    try:
        call(*args, **kwargs)
    except AppError as error:
        return error.code
    return None


def form(**changes):
    """가짜 이름만 쓴 폼 값(실제 블로그 이름·아이디가 아니다)."""
    values = {"display_name": "예시 블로그 가", "blog_ref": "example-blog-a", "alias": "예시 별명", "channel_role": "예시 역할", "main_topics": ("예시 주제 하나", "예시 주제 둘"), "audience": "예시 독자",
              "tone": "예시 문체", "categories": ("예시 분류 1", "예시 분류 2"), "intro": "예시 소개글 한 줄", "color_preset": "warm_lifestyle"}
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
        return bp.read_snapshot(self.ctx)

    def bytes_of(self, path=None):
        path = path or self.paths.profiles
        return path.read_bytes() if path.exists() else None

    def tree(self):
        return ss.tree_snapshot(self.root)

    def leftovers(self):
        """남으면 안 되는 것 — 임시 파일(`*.tmp`)과 잠금 파일."""
        return sorted(path.relative_to(self.root).as_posix() for path in self.root.rglob("*") if path.is_file() and (path.name.endswith(".tmp") or path.name.endswith(".lock")))

    def save(self, key="naver_a", fields=None, version=None):
        return bp.save_slot(self.ctx, key, form() if fields is None else fields, expected_version=self.snap().version if version is None else version)

    def put_profiles(self, mutate):
        """파일을 미리 만들어 둔다(`mutate(프로필 목록) → 프로필 목록`) — 사람이 JSON 을 고친 것처럼 `write_json` 으로 쓴다."""
        profiles = mutate(channels.default_profiles())
        self.paths.folder.mkdir(parents=True, exist_ok=True)
        self.paths.profiles.write_text(json.dumps(channels.profiles_to_dict(profiles), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


# ---- 슬롯 규칙(순수) --------------------------------------------------------------------------------------------------------------
class SlotRulesTest(unittest.TestCase):
    def test_the_five_slots_and_the_three_kinds_are_the_ones_the_operator_fixed(self):
        self.assertEqual(bp.SLOTS, ("github_pages", "blogger_en", "blogger_ko", "naver_a", "naver_b"))
        self.assertEqual(sorted(sum(bp.SLOT_KINDS, ())), sorted(bp.SLOTS))
        self.assertEqual(bp.kind_of("naver_a"), ("naver_a", "naver_b"))
        self.assertEqual(bp.kind_of("blogger_en"), ("blogger_ko", "blogger_en"))
        self.assertEqual(bp.kind_of("github_pages"), ("github_pages",))
        for bad in ("naver_c", "", None, 3, "blogger_a"):
            with self.assertRaises(ValueError):
                bp.check_slot(bad)

    def test_only_the_two_naver_slots_have_the_candidate_generation_field(self):
        for key in bp.SLOTS:
            fields = bp.form_fields(key)
            self.assertEqual("generation_enabled" in fields, key in ("naver_a", "naver_b"), key)
            self.assertEqual(fields[:len(bp.COMMON_FIELDS)], bp.COMMON_FIELDS)

    def test_the_form_fields_are_real_channel_profile_fields_and_leave_the_engine_fields_alone(self):
        names = {field.name for field in dataclasses.fields(channels.ChannelProfile)}
        for key in bp.SLOTS:
            self.assertLessEqual(set(bp.form_fields(key)), names, key)
        engine = {"weights", "top_n", "cluster_cap", "subheading_min", "trend_use", "dup_cutoffs", "topic_clusters", "expansion_directions", "evergreen_pct", "realtime_pct", "history_enabled", "key",
                  "priority_keywords", "exclude_keywords", "preferred_post_types", "home_regions", "day_trip_regions"}
        self.assertEqual(set(bp.COMMON_FIELDS) & engine, set())
        self.assertLessEqual(set(bp.TEXT_FIELDS), set(bp.COMMON_FIELDS))
        self.assertLessEqual(set(bp.TEXT_FIELDS), set(channels.PROFILE_FIELD_KO))

    def test_the_key_shape_checked_text_fields_are_pinned_to_the_eleven_user_written_fields(self):
        """M1(독립 검증) — 키 모양 검사 대상 칸은 시험이 자기 상수를 돌려 쓰지 않도록 글 칸 열한 개를 직접 못박는다(목록에서 한 칸이 빠지면 그 칸에는 비밀 모양이 그대로 저장된다)."""
        self.assertEqual(bp.TEXT_FIELDS, ("display_name", "blog_ref", "alias", "channel_role", "main_topics", "audience", "tone", "categories", "intro", "profile_image", "cover_image"))
        self.assertEqual(len(set(bp.TEXT_FIELDS)), 11)

    def test_a_fresh_default_slot_is_empty_and_unregistered_and_one_changed_field_makes_it_not_empty(self):
        for profile in channels.default_profiles():
            self.assertTrue(bp.is_empty(profile), profile.key)
            self.assertFalse(bp.is_registered(profile), profile.key)
        base = bp.default_profile("naver_a")
        for change in ({"display_name": "다른 이름"}, {"blog_ref": "example-blog-a"}, {"alias": "예시"}, {"generation_enabled": False}, {"color_preset": "cool_technology"}, {"monetization_focus": ()}):
            with self.subTest(change=change):
                other = dataclasses.replace(base, **change)
                self.assertFalse(bp.is_empty(other))
        self.assertTrue(bp.is_registered(dataclasses.replace(base, blog_ref="example-blog-a")))
        for engine in ({"top_n": 7}, {"history_enabled": False}, {"priority_keywords": ("예시 우선",)}):
            self.assertTrue(bp.is_empty(dataclasses.replace(base, **engine)), "엔진 칸·씨앗 칸은 '비어 있음' 에 영향이 없다")

    def test_the_clone_target_is_the_other_empty_slot_of_the_same_kind_and_nothing_otherwise(self):
        profiles = channels.default_profiles()
        self.assertEqual(bp.clone_target(profiles, "naver_a"), "naver_b")
        self.assertEqual(bp.clone_target(profiles, "blogger_ko"), "blogger_en")
        self.assertIsNone(bp.clone_target(profiles, "github_pages"))
        taken = tuple(dataclasses.replace(p, alias="예시") if p.key == "naver_b" else p for p in profiles)
        self.assertIsNone(bp.clone_target(taken, "naver_a"))
        self.assertEqual(bp.clone_target(taken, "naver_b"), "naver_a")


# ---- 읽기 -------------------------------------------------------------------------------------------------------------------------
class ReadTest(Base):
    def test_a_missing_file_reads_as_the_five_default_profiles_and_nothing_is_created(self):
        before = sorted(str(path) for path in self.tmp.rglob("*"))
        snap = self.snap()
        self.assertEqual((snap.version, snap.state), (bp.VERSION_MISSING, tf.STATE_MISSING))
        self.assertEqual(snap.profiles, channels.default_profiles())
        self.assertEqual(sorted(str(path) for path in self.tmp.rglob("*")), before, "읽기는 파일도 폴더도 만들지 않는다")
        self.assertFalse(self.paths.folder.exists())

    def test_a_zero_byte_file_is_treated_as_not_there_yet_and_is_not_touched_by_reading(self):
        self.paths.folder.mkdir(parents=True)
        self.paths.profiles.write_bytes(b"")
        snap = self.snap()
        self.assertEqual((snap.state, snap.profiles), (tf.STATE_MISSING, channels.default_profiles()))
        self.assertNotEqual(snap.version, bp.VERSION_MISSING, "0바이트 파일은 있는 파일이라 판이 `missing` 과 다르다(저장하면 그 파일을 대신한다)")
        self.assertEqual(self.paths.profiles.read_bytes(), b"")

    def test_a_good_file_reads_back_with_a_version_that_follows_the_content(self):
        self.save()
        first = self.snap()
        self.assertEqual(first.state, tf.STATE_OK)
        self.assertEqual(self.snap().version, first.version, "같은 내용은 같은 판")
        self.save("naver_a", {"alias": "바뀐 별명"})
        self.assertNotEqual(self.snap().version, first.version)

    def test_an_unreadable_or_wrong_file_stops_with_an_error_and_is_never_fixed_or_overwritten(self):
        self.paths.folder.mkdir(parents=True)
        good = channels.profiles_to_dict(channels.default_profiles())
        bad_value = json.loads(json.dumps(good))
        bad_value["profiles"][3]["language"] = "fr"
        cases = ((b"{broken", "TOPIC_FILE_INVALID"), (b"\xff\xfe\x00", "TOPIC_FILE_INVALID"), (b"[1]", "CONTENT_INVALID"), (json.dumps({**good, "schema": 9}).encode(), "CONTENT_INVALID"),
                 (json.dumps(bad_value).encode(), "CONTENT_INVALID"))
        for raw, code in cases:
            with self.subTest(raw=raw[:20]):
                self.paths.profiles.write_bytes(raw)
                self.assertEqual(code_of(bp.read_snapshot, self.ctx), code)
                self.assertEqual(code_of(bp.save_slot, self.ctx, "naver_a", form(), expected_version="x" * 64), code, "틀린 파일 위에는 쓰지 않는다")
                self.assertEqual(self.paths.profiles.read_bytes(), raw)
        self.paths.profiles.unlink()
        self.paths.profiles.mkdir()
        self.assertEqual(code_of(bp.read_snapshot, self.ctx), "TOPIC_FILE_INVALID", "파일 자리에 폴더가 있다")

    def test_a_file_with_key_shaped_text_in_a_profile_text_field_is_not_read(self):
        profiles = channels.default_profiles()
        poisoned = tuple(dataclasses.replace(p, intro="소개 " + KEY_SHAPED) if p.key == "naver_a" else p for p in profiles)
        self.paths.folder.mkdir(parents=True)
        self.paths.profiles.write_text(json.dumps(channels.profiles_to_dict(poisoned)), encoding="utf-8")
        self.assertEqual(code_of(bp.read_snapshot, self.ctx), "CONTENT_INVALID")

    def test_a_version_one_file_reads_and_keeps_its_engine_values(self):
        data = channels.profiles_to_dict(channels.default_profiles())
        data["schema"] = 1
        data["profiles"] = [{name: value for name, value in item.items() if name in channels._KEYS_V1} for item in data["profiles"]]
        self.paths.folder.mkdir(parents=True)
        self.paths.profiles.write_text(json.dumps(data), encoding="utf-8")
        snap = self.snap()
        self.assertEqual(snap.state, tf.STATE_OK)
        self.assertEqual(snap.profiles, channels.default_profiles(), "판 1 은 새 칸이 빈 기본값으로 채워진다")


# ---- 저장 -------------------------------------------------------------------------------------------------------------------------
class SaveTest(Base):
    def test_the_first_save_creates_the_folder_and_a_file_with_all_five_profiles_and_changes_only_the_form_fields(self):
        saved = self.save()
        self.assertEqual((saved.kind, saved.changed, saved.backed_up), ("saved", ("naver_a",), False))
        data = json.loads(self.paths.profiles.read_text(encoding="utf-8"))
        self.assertEqual((data["schema"], [item["key"] for item in data["profiles"]]), (2, list(channels.CHANNELS)))
        mine = next(item for item in data["profiles"] if item["key"] == "naver_a")
        self.assertEqual((mine["display_name"], mine["blog_ref"], mine["alias"], mine["main_topics"], mine["color_preset"]), ("예시 블로그 가", "example-blog-a", "예시 별명", ["예시 주제 하나", "예시 주제 둘"], "warm_lifestyle"))
        for item in data["profiles"]:
            if item["key"] != "naver_a":
                self.assertEqual(item, next(p for p in channels.default_profiles() if p.key == item["key"]).to_dict(), "다른 슬롯은 기본 그대로")
        base = bp.default_profile("naver_a").to_dict()
        for name in ("weights", "top_n", "cluster_cap", "trend_use", "topic_clusters", "expansion_directions", "evergreen_pct", "realtime_pct", "history_enabled", "priority_keywords", "exclude_keywords"):
            self.assertEqual(mine[name], base[name], name)

    def test_engine_values_and_unseen_fields_edited_by_hand_survive_a_save(self):
        def tweak(profiles):
            return tuple(dataclasses.replace(p, top_n=9, priority_keywords=("예시 우선",), exclude_keywords=("예시 제외",), preferred_post_types=("정보형",), home_regions=("예시 지역",),
                                             history_enabled=False, monetization_focus=("small_appliance", "my_custom_tag")) if p.key == "naver_a" else p for p in profiles)
        self.put_profiles(tweak)
        saved = bp.save_slot(self.ctx, "naver_a", form(monetization_focus=("small_appliance", "my_custom_tag", "ai_service")), expected_version=self.snap().version)
        mine = {p.key: p for p in saved.snapshot.profiles}["naver_a"]
        self.assertEqual((mine.top_n, mine.priority_keywords, mine.exclude_keywords, mine.preferred_post_types, mine.home_regions, mine.history_enabled), (9, ("예시 우선",), ("예시 제외",), ("정보형",), ("예시 지역",), False))
        self.assertEqual(mine.monetization_focus, ("small_appliance", "my_custom_tag", "ai_service"))

    def test_a_save_without_any_change_writes_nothing_and_creates_no_lock_or_folder(self):
        saved = self.save()
        before, listing = self.tree(), sorted(str(p) for p in self.tmp.rglob("*"))
        again = bp.save_slot(self.ctx, "naver_a", form(), expected_version=saved.snapshot.version)
        self.assertEqual((again.kind, again.changed, again.backed_up), ("unchanged", (), False))
        self.assertEqual(self.tree(), before)
        self.assertEqual(sorted(str(p) for p in self.tmp.rglob("*")), listing, "바뀐 것이 없으면 잠금도 임시 파일도 만들지 않는다")
        fresh = tempfile.TemporaryDirectory()
        self.addCleanup(fresh.cleanup)
        other = ss.make_ctx(fresh.name)
        done = bp.save_slot(other, "naver_a", {"display_name": bp.default_profile("naver_a").display_name}, expected_version=bp.VERSION_MISSING)
        self.assertEqual(done.kind, "unchanged")
        self.assertFalse(tf.topic_paths(other.workspace).folder.exists(), "기본 그대로 저장해도 파일을 만들지 않는다")

    def test_wrong_values_are_reported_per_field_and_nothing_is_written(self):
        self.save()
        before, listing = self.tree(), sorted(str(p) for p in self.tmp.rglob("*"))
        cases = {"alias": "가" * (channels.MAX_ALIAS + 1), "blog_ref": "공백 있는 아이디", "language": "fr", "main_topics": ["같음", "같음"], "intro": "한 줄 <script>x</script>", "color_preset": "neon",
                 "profile_image": "data:image/png;base64,xx", "monetization_focus": ["Not A Tag"], "display_name": ""}
        for name, value in cases.items():
            with self.subTest(field=name):
                with self.assertRaises(bp.ProfileProblems) as caught:
                    bp.save_slot(self.ctx, "naver_a", {name: value}, expected_version=self.snap().version)
                self.assertEqual(caught.exception.problems, {name: "invalid"})
                self.assertEqual(caught.exception.code, "CONTENT_INVALID")
        with self.assertRaises(bp.ProfileProblems) as caught:
            bp.save_slot(self.ctx, "naver_a", {"alias": "가" * 99, "blog_ref": "x y", "language": "fr"}, expected_version=self.snap().version)
        self.assertEqual(sorted(caught.exception.problems), ["alias", "blog_ref", "language"], "틀린 칸을 한꺼번에 모두 알린다")
        self.assertEqual(self.tree(), before)
        self.assertEqual(sorted(str(p) for p in self.tmp.rglob("*")), listing)

    def test_key_shaped_text_is_refused_before_anything_is_written_and_names_the_fields(self):
        self.save()
        before = self.tree()
        for name in bp.TEXT_FIELDS:
            value = (KEY_SHAPED,) if name in ("main_topics", "categories") else KEY_SHAPED
            with self.subTest(field=name):
                with self.assertRaises(bp.ProfileProblems) as caught:
                    bp.save_slot(self.ctx, "naver_a", {name: value}, expected_version=self.snap().version)
                self.assertEqual(caught.exception.problems, {name: "key_shape"})
                self.assertEqual(caught.exception.code, "CONTENT_INVALID")
        self.assertEqual(self.tree(), before, "표시 이름의 키 모양은 읽을 때는 안 걸리지만 백업이 막히므로 저장 전에 거른다 — 아무것도 쓰지 않았다")
        self.assertNotIn(KEY_SHAPED, repr(caught.exception.problems) + str(caught.exception) + caught.exception.detail + caught.exception.log_line(), "오류에 입력한 값이 없다")

    def test_a_saved_file_always_reads_back_and_passes_the_backup_check(self):
        """이 화면이 저장한 파일을 이 앱이 못 읽거나 백업이 막히는 일이 없다."""
        from chanceblog_desktop.service import topics as topic_service
        self.save()
        self.save("naver_b", form(display_name="예시 블로그 나", blog_ref="https://blog.naver.com/example-blog-b", color_preset="cool_technology", language="ko"))
        self.assertEqual(len(tf.load_profiles(self.paths).value), 5)
        made = topic_service.backup_topics(self.ctx)
        self.assertIn(layout.CHANNEL_PROFILES_FILE, made.files)

    def test_the_generation_switch_belongs_to_the_naver_slots_only_and_hand_edited_values_of_the_others_stay(self):
        saved = self.save("naver_a", form(generation_enabled=False))
        self.assertFalse({p.key: p for p in saved.snapshot.profiles}["naver_a"].generation_enabled)
        self.assertTrue({p.key: p for p in saved.snapshot.profiles}["naver_b"].generation_enabled)
        with self.assertRaises(ValueError):
            bp.save_slot(self.ctx, "blogger_ko", {"generation_enabled": True}, expected_version=self.snap().version)
        with self.assertRaises(ValueError):
            bp.save_slot(self.ctx, "naver_a", {"no_such_field": 1}, expected_version=self.snap().version)
        self.put_profiles(lambda profiles: tuple(dataclasses.replace(p, generation_enabled=True) if p.key == "blogger_ko" else p for p in profiles))
        done = bp.save_slot(self.ctx, "blogger_ko", form(display_name="예시 블로그 다", language="ko"), expected_version=self.snap().version)
        self.assertTrue({p.key: p for p in done.snapshot.profiles}["blogger_ko"].generation_enabled, "화면이 모르는 값은 손으로 고친 대로 보존된다")

    def test_a_stale_version_writes_nothing_and_says_conflict(self):
        first = self.snap().version
        self.save()
        before = self.tree()
        self.assertEqual(code_of(bp.save_slot, self.ctx, "naver_b", form(), expected_version=first), "STORE_CONFLICT")
        self.assertEqual(self.tree(), before)
        self.assertEqual(code_of(bp.save_slot, self.ctx, "naver_b", form(), expected_version="not-a-version"), "STORE_CONFLICT")
        self.assertEqual(code_of(bp.clear_slot, self.ctx, "naver_a", confirmed=True, expected_version=first), "STORE_CONFLICT")
        self.assertEqual(code_of(bp.clone_slot, self.ctx, "naver_a", "naver_b", expected_version=first), "STORE_CONFLICT")
        self.assertEqual(self.tree(), before)

    def test_a_file_changed_by_hand_after_the_screen_read_it_is_not_overwritten(self):
        self.save()
        seen = self.snap().version
        self.put_profiles(lambda profiles: tuple(dataclasses.replace(p, alias="손으로 고친 별명") if p.key == "naver_b" else p for p in profiles))
        hand = self.bytes_of()
        self.assertEqual(code_of(bp.save_slot, self.ctx, "naver_a", form(alias="다른 별명"), expected_version=seen), "STORE_CONFLICT")
        self.assertEqual(self.bytes_of(), hand)

    def test_every_edit_changes_only_the_files_it_may_touch(self):
        """다른 파일(보관함·씨앗·캘린더·글 보관함·설정·연결 설정·사용량 기록)은 바이트까지 그대로다 — 새로 생기거나 바뀌는 것은 프로필 파일·사본·(지나간) 잠금뿐이다."""
        self.paths.folder.mkdir(parents=True)
        others = {self.paths.database: b"SQLite format 3\0example", self.paths.seeds: b'{"schema": 2, "seeds": []}\n', self.paths.calendar: b'{"schema": 1, "entries": []}\n',
                  self.ctx.workspace.store_path: b"example store bytes", self.ctx.workspace.connections_path: b'{"schema": 1}', self.ctx.workspace.quota_path: b'{"schema": 1}'}
        for path, data in others.items():
            path.write_bytes(data)
        before = self.tree()
        self.save()
        saved = self.save("naver_a", {"alias": "바뀐 별명"})
        self.assertTrue(saved.backed_up)
        bp.clone_slot(self.ctx, "naver_a", "naver_b", expected_version=self.snap().version)
        bp.clear_slot(self.ctx, "naver_b", confirmed=True, expected_version=self.snap().version)
        after = self.tree()
        changed = {name for name in set(before) | set(after) if before.get(name) != after.get(name)}
        self.assertEqual(changed, {"topic_engine/channel_profiles.json", "topic_engine/channel_profiles.json.bak"})
        for path, data in others.items():
            self.assertEqual(path.read_bytes(), data, path.name)
        self.assertEqual(self.leftovers(), [])


# ---- 백업 -------------------------------------------------------------------------------------------------------------------------
class BackupTest(Base):
    def test_every_save_after_the_first_keeps_the_previous_valid_content_in_a_bak_file(self):
        self.save()
        first = self.bytes_of()
        saved = self.save("naver_a", {"alias": "바뀐 별명"})
        self.assertTrue(saved.backed_up)
        bak = self.paths.profiles.with_name(bp.BACKUP_NAME)
        self.assertEqual(json.loads(bak.read_bytes()), json.loads(first), "직전의 올바른 내용")
        self.assertEqual(bak.read_bytes(), first, "write_json 이 쓴 파일이면 사본의 바이트도 같다")
        self.save("naver_a", {"alias": "또 바뀐 별명"})
        self.assertEqual(json.loads(bak.read_bytes())["profiles"][3]["alias"], "바뀐 별명", "사본은 늘 직전 하나")

    def test_a_version_one_file_gets_an_old_shape_copy_before_it_is_upgraded(self):
        data = channels.profiles_to_dict(channels.default_profiles())
        data["schema"] = 1
        data["profiles"] = [{name: value for name, value in item.items() if name in channels._KEYS_V1} for item in data["profiles"]]
        self.paths.folder.mkdir(parents=True)
        original = (json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
        self.paths.profiles.write_bytes(original)
        saved = self.save()
        old = self.paths.folder / "channel_profiles.json.v1.bak"
        self.assertEqual(old.read_bytes(), original, "옛 모양 그대로의 사본")
        self.assertEqual(json.loads(self.bytes_of())["schema"], 2)
        self.assertTrue(saved.backed_up)

    def test_when_the_backup_cannot_be_written_the_main_file_is_not_touched(self):
        self.save()
        before = self.tree()
        os.mkdir(self.paths.profiles.with_name(bp.BACKUP_NAME))                 # 사본 자리에 폴더 — 어느 운영체제에서나 사본을 쓸 수 없다
        before = self.tree()
        self.assertEqual(code_of(bp.save_slot, self.ctx, "naver_a", {"alias": "바뀌면 안 되는 별명"}, expected_version=self.snap().version), "FILE_WRITE_FAILED")
        self.assertEqual(self.tree(), before, "사본을 못 남기면 본 파일을 쓰지 않는다(원본 유지)")
        self.assertEqual(self.leftovers(), [])

    def test_a_zero_byte_file_has_nothing_to_back_up_and_is_replaced(self):
        self.paths.folder.mkdir(parents=True)
        self.paths.profiles.write_bytes(b"")
        saved = self.save(version=self.snap().version)
        self.assertEqual((saved.kind, saved.backed_up), ("saved", False))
        self.assertEqual(self.snap().state, tf.STATE_OK)
        self.assertFalse(self.paths.profiles.with_name(bp.BACKUP_NAME).exists())


# ---- 복제·삭제 ----------------------------------------------------------------------------------------------------------------
class CloneAndClearTest(Base):
    def test_clone_copies_the_form_fields_into_the_empty_slot_of_the_same_kind_only(self):
        self.save("naver_a", form(generation_enabled=False))
        cloned = bp.clone_slot(self.ctx, "naver_a", "naver_b", expected_version=self.snap().version)
        self.assertEqual((cloned.kind, cloned.changed), ("saved", ("naver_b",)))
        by_key = {p.key: p for p in cloned.snapshot.profiles}
        for name in bp.form_fields("naver_a"):
            self.assertEqual(getattr(by_key["naver_b"], name), getattr(by_key["naver_a"], name), name)
        self.assertEqual((by_key["naver_b"].weights, by_key["naver_b"].topic_clusters), (bp.default_profile("naver_b").weights, bp.default_profile("naver_b").topic_clusters), "엔진 칸은 복사하지 않는다")

    def test_clone_never_overwrites_and_needs_a_registered_source_and_a_same_kind_target(self):
        self.save("naver_a", form())
        self.save("naver_b", form(display_name="예시 블로그 나", blog_ref="example-blog-b"))
        before = self.tree()
        self.assertEqual(code_of(bp.clone_slot, self.ctx, "naver_a", "naver_b", expected_version=self.snap().version), "CONTENT_INVALID", "덮어쓰기 금지")
        self.assertEqual(self.tree(), before)
        with self.assertRaises(ValueError):
            bp.clone_slot(self.ctx, "naver_a", "blogger_ko", expected_version=self.snap().version)
        with self.assertRaises(ValueError):
            bp.clone_slot(self.ctx, "naver_a", "naver_a", expected_version=self.snap().version)
        self.assertEqual(code_of(bp.clone_slot, self.ctx, "blogger_ko", "blogger_en", expected_version=self.snap().version), "CONTENT_INVALID", "블로그가 등록되지 않은 슬롯은 복제할 것이 없다")
        self.assertEqual(self.tree(), before)

    def test_a_slot_with_only_a_changed_name_is_not_empty_so_it_is_not_overwritten_either(self):
        self.save("naver_a", form())
        self.save("naver_b", {"display_name": "이름만 바꾼 슬롯"})
        self.assertEqual(code_of(bp.clone_slot, self.ctx, "naver_a", "naver_b", expected_version=self.snap().version), "CONTENT_INVALID")
        self.assertEqual({p.key: p for p in self.snap().profiles}["naver_b"].display_name, "이름만 바꾼 슬롯")

    def test_clear_needs_the_real_true_and_reads_nothing_without_it(self):
        self.save()
        before = self.tree()
        for value in (False, None, 1, "yes", "true", [True]):
            with self.subTest(confirmed=value):
                with mock.patch.object(bp, "_read", side_effect=AssertionError("읽으면 안 된다")):
                    self.assertEqual(code_of(bp.clear_slot, self.ctx, "naver_a", confirmed=value, expected_version="x"), "CONFIRMATION_REQUIRED")
        self.assertEqual(self.tree(), before)
        with self.assertRaises(TypeError):
            bp.clear_slot(self.ctx, "naver_a", expected_version="x")

    def test_clear_empties_the_slot_but_the_slot_stays_and_engine_values_stay(self):
        self.put_profiles(lambda profiles: tuple(dataclasses.replace(p, top_n=9, priority_keywords=("예시 우선",)) if p.key == "naver_a" else p for p in profiles))
        self.save()
        self.save("naver_b", form(display_name="예시 블로그 나", blog_ref="example-blog-b"))
        cleared = bp.clear_slot(self.ctx, "naver_a", confirmed=True, expected_version=self.snap().version)
        by_key = {p.key: p for p in cleared.snapshot.profiles}
        self.assertEqual(tuple(by_key), bp.SLOTS, "다섯 슬롯은 늘 그대로")
        self.assertTrue(bp.is_empty(by_key["naver_a"]))
        self.assertFalse(bp.is_registered(by_key["naver_a"]))
        self.assertEqual((by_key["naver_a"].top_n, by_key["naver_a"].priority_keywords), (9, ("예시 우선",)), "엔진 칸·씨앗 칸은 그대로")
        self.assertEqual(by_key["naver_b"].blog_ref, "example-blog-b", "다른 슬롯은 그대로")
        self.assertEqual(by_key["naver_a"].display_name, bp.default_profile("naver_a").display_name, "이름은 기본 이름으로")
        again = bp.clear_slot(self.ctx, "naver_a", confirmed=True, expected_version=cleared.snapshot.version)
        self.assertEqual(again.kind, "unchanged", "이미 빈 슬롯을 지워도 아무것도 쓰지 않는다")

    def test_clearing_a_slot_does_not_touch_the_things_made_with_that_profile(self):
        """후보·초안·발행 기록(보관함 파일)과 키 보관소는 이 일이 건드리지 않는다 — 지우기 전후 보관함 파일이 바이트까지 같다."""
        self.save()
        self.paths.database.write_bytes(b"SQLite format 3\0candidates of naver_a")
        self.ctx.workspace.store_path.write_bytes(b"example drafts and published records")
        before = (self.paths.database.read_bytes(), self.ctx.workspace.store_path.read_bytes(), self.ctx.keystore.__dict__.copy())
        bp.clear_slot(self.ctx, "naver_a", confirmed=True, expected_version=self.snap().version)
        self.assertEqual((self.paths.database.read_bytes(), self.ctx.workspace.store_path.read_bytes(), self.ctx.keystore.__dict__.copy()), before)


# ---- 실패 주입 ---------------------------------------------------------------------------------------------------------------------
class Injector:
    """진짜 `os` 의 열기·쓰기·`fsync`·닫기·이름 바꾸기를 부르면서 원하는 곳(파일 이름 + 그 파일에 대한 n 번째 호출)에서 실패를 끼운다. `after` 면 일을 한 **뒤에** 끼운다(이름을 바꾼 직후 같은 때)."""

    def __init__(self, case):
        self.paths_of = {}
        self.rules = []
        self.counts = {}
        self.log = []
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
        if name == "replace":
            return Path(os.fspath(args[1])).name
        if name == "open":
            return Path(os.fspath(args[0])).name
        return self.paths_of.get(args[0], "?")


def writing_error(number=errno.EIO):
    return OSError(number, os.strerror(number))


class FailureInjectionTest(Base):
    """쓰기 중 어디서 실패해도(백업·본 파일의 임시 파일·디스크 내려보내기·이름 바꾸기 직전·직후 검증·백업 자리·읽기 전용·디스크 가득) 기존 값이 보존되고 다시 하면 된다."""
    MAIN = "channel_profiles.json"

    def setUp(self):
        super().setUp()
        self.save()                                                                  # 이미 저장된 프로필이 있는 PC(백업 규칙까지 보려고 한 번 더)
        self.save("naver_a", {"alias": "저장된 별명"})
        self.before = self.tree()
        self.injector = Injector(self)

    def inject(self, op, filename, number=errno.EIO, **kwargs):
        self.injector.when(op, filename, writing_error(number), **kwargs)

    def try_save(self):
        return code_of(bp.save_slot, self.ctx, "naver_a", {"alias": "실패해야 하는 별명"}, expected_version=self.snap().version)

    def assert_untouched(self, code, expected):
        self.assertEqual(code, expected)
        self.assertEqual(self.tree(), self.before, "기존 값(본 파일·사본·다른 파일)이 한 바이트도 안 바뀌었다")
        self.assertEqual(self.leftovers(), [], "임시 파일·잠금 파일이 남지 않았다")

    def assert_retry_works(self):
        for name in REAL:
            setattr(os, name, REAL[name])
        saved = bp.save_slot(self.ctx, "naver_a", {"alias": "다시 한 별명"}, expected_version=self.snap().version)
        self.assertEqual(saved.kind, "saved")
        self.assertEqual({p.key: p for p in self.snap().profiles}["naver_a"].alias, "다시 한 별명")

    def test_the_backup_temp_file_fails_while_being_written(self):
        self.inject("write", bp.BACKUP_NAME + ".tmp")
        self.assert_untouched(self.try_save(), "FILE_WRITE_FAILED")
        self.assert_retry_works()

    def test_the_backup_cannot_be_put_in_place(self):
        self.inject("replace", bp.BACKUP_NAME)
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
        self.inject("write", bp.BACKUP_NAME + ".tmp", errno.ENOSPC)
        self.assert_untouched(self.try_save(), "DISK_FULL")
        self.assert_retry_works()

    def test_a_new_file_that_reads_back_differently_is_rolled_back_to_the_previous_content(self):
        """이름을 바꾼 **직후** 파일이 다르게 읽히면(디스크·다른 프로그램) 직전 내용으로 되돌리고 실패로 알린다."""
        def corrupt(args):
            Path(os.fspath(args[1])).write_bytes(b"{garbage")

        self.injector.when("replace", self.MAIN, after=corrupt)
        code = self.try_save()
        self.assertEqual(code, "FILE_WRITE_FAILED")
        self.assertEqual(self.tree(), {**self.before, "topic_engine/channel_profiles.json.bak": self.tree()["topic_engine/channel_profiles.json.bak"]}, "본 파일은 직전 내용으로 돌아왔다(내용이 같다)")
        self.assertEqual(json.loads(self.bytes_of()), json.loads(self.before["topic_engine/channel_profiles.json"]))
        self.assertEqual(self.snap().profiles, tf.load_profiles(self.paths).value)
        self.assertEqual(self.leftovers(), [])
        self.assert_retry_works()

    def test_when_even_the_rollback_fails_the_error_says_so_and_the_previous_content_is_still_in_the_backup(self):
        def corrupt(args):
            Path(os.fspath(args[1])).write_bytes(b"{garbage")

        self.injector.when("replace", self.MAIN, after=corrupt)
        self.injector.when("replace", self.MAIN, writing_error(), nth=2)             # 되돌리는 이름 바꾸기도 실패
        with self.assertRaises(AppError) as caught:
            bp.save_slot(self.ctx, "naver_a", {"alias": "실패해야 하는 별명"}, expected_version=self.snap().version)
        self.assertEqual(caught.exception.code, "FILE_WRITE_FAILED")
        self.assertIn("되돌리지도 못했다", caught.exception.detail)
        bak = self.paths.profiles.with_name(bp.BACKUP_NAME)
        self.assertEqual(json.loads(bak.read_bytes()), json.loads(self.before["topic_engine/channel_profiles.json"]), "직전 내용은 사본에 그대로 있다")
        self.assertEqual(self.leftovers(), [])

    def test_the_lock_is_released_after_every_kind_of_failure(self):
        self.inject("write", self.MAIN + ".tmp")
        self.assertEqual(self.try_save(), "FILE_WRITE_FAILED")
        self.assertFalse((self.ctx.workspace.locks_dir / (bp.LOCK_NAME + ".lock")).exists())


class UnwritableFilesTest(Base):
    """읽기 전용 파일·폴더 — 쓰기 실패가 쉬운 오류가 되고 앱이 죽지 않으며 기존 값이 보존된다(운영체제가 막는 진짜 방법으로)."""

    def setUp(self):
        super().setUp()
        self.save()
        self.save("naver_a", {"alias": "저장된 별명"})
        self.before = self.tree()

    @contextlib.contextmanager
    def read_only(self):
        """윈도는 프로필 파일에 읽기 전용 표시(이름 바꾸기로 덮을 수 없다), 그 밖은 `topic_engine` 폴더의 쓰기 권한을 뺀다. 권한을 빼도 쓸 수 있는 환경(관리자 권한)이면 시험을 건너뛴다."""
        target = self.paths.profiles if os.name == "nt" else self.paths.folder
        original = stat.S_IMODE(target.stat().st_mode)
        os.chmod(target, stat.S_IREAD if os.name == "nt" else stat.S_IRUSR | stat.S_IXUSR)
        try:
            if os.name != "nt" and os.access(self.paths.folder, os.W_OK):
                self.skipTest("이 환경에서는 쓰기 권한을 빼도 쓸 수 있다(관리자 권한)")
            yield
        finally:
            os.chmod(target, original | stat.S_IWRITE)

    def test_a_read_only_profile_file_cannot_be_replaced_and_stays_as_it_was(self):
        with self.read_only():
            code = code_of(bp.save_slot, self.ctx, "naver_a", {"alias": "바뀌면 안 되는 별명"}, expected_version=self.snap().version)
        self.assertEqual(code, "FILE_WRITE_FAILED")
        self.assertEqual(self.tree(), self.before)
        self.assertEqual(self.leftovers(), [])
        saved = bp.save_slot(self.ctx, "naver_a", {"alias": "풀린 뒤 별명"}, expected_version=self.snap().version)
        self.assertEqual(saved.kind, "saved")

    def test_a_lock_folder_that_cannot_be_made_is_a_plain_error(self):
        blocker = self.root / "locks"
        if blocker.exists():
            for item in blocker.iterdir():
                item.unlink()
            blocker.rmdir()
        blocker.write_bytes(b"not a folder")                                          # `locks` 자리에 파일 — 잠금 파일을 만들 수 없다
        code = code_of(bp.save_slot, self.ctx, "naver_a", {"alias": "바뀌면 안 되는 별명"}, expected_version=self.snap().version)
        self.assertEqual(code, "FILE_WRITE_FAILED")
        self.assertEqual(self.paths.profiles.read_bytes(), self.before["topic_engine/channel_profiles.json"])


# ---- 잠금·동시 저장 ----------------------------------------------------------------------------------------------------------------
class ConcurrencyTest(Base):
    def run_pair(self, *, second_wait):
        """창 둘이 같은 판에서 읽고 저장한다: 첫째가 잠금 안(백업을 쓰는 중)에 멈춰 있는 동안 둘째가 저장하려 한다 → (첫째 결과, 둘째 결과 또는 오류 코드, 처음 읽은 판)."""
        seen = self.snap().version
        inside, go = threading.Event(), threading.Event()
        real = bp._backup
        results = {}

        def slow(paths, raw):
            inside.set()
            self.assertTrue(go.wait(15))
            return real(paths, raw)

        def first():
            results["first"] = bp.save_slot(self.ctx, "naver_a", form(), expected_version=seen)

        def second():
            try:
                results["second"] = bp.save_slot(self.ctx, "naver_b", form(display_name="예시 블로그 나", blog_ref="example-blog-b"), expected_version=seen, wait=second_wait)
            except AppError as error:
                results["second"] = error.code

        with mock.patch.object(bp, "_backup", slow):
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
        results, seen = self.run_pair(second_wait=10.0)
        self.assertEqual(results["first"].kind, "saved")
        self.assertEqual(results["second"], "STORE_CONFLICT", "잠금을 넘겨받은 뒤 판을 다시 보니 낡았다 — 아무것도 쓰지 않았다")
        by_key = {p.key: p for p in tf.load_profiles(self.paths).value}
        self.assertEqual(by_key["naver_a"].blog_ref, "example-blog-a")
        self.assertEqual(by_key["naver_b"].blog_ref, "", "진 쪽의 변경은 파일에 없다(잃어버린 갱신이 아니라 거절)")
        again = bp.save_slot(self.ctx, "naver_b", form(display_name="예시 블로그 나", blog_ref="example-blog-b"), expected_version=self.snap().version)
        self.assertEqual(again.kind, "saved", "다시 불러온 뒤에는 저장된다")
        self.assertEqual({p.key: p.blog_ref for p in tf.load_profiles(self.paths).value if p.key.startswith("naver")}, {"naver_a": "example-blog-a", "naver_b": "example-blog-b"})
        self.assertEqual(self.leftovers(), [])

    def test_a_lock_held_by_another_window_makes_the_save_give_up_without_changing_anything(self):
        results, seen = self.run_pair(second_wait=0.3)
        self.assertEqual(results["first"].kind, "saved")
        self.assertEqual(results["second"], "TOPIC_STORE_LOCKED")
        self.assertEqual({p.key: p.blog_ref for p in tf.load_profiles(self.paths).value if p.key.startswith("naver")}, {"naver_a": "example-blog-a", "naver_b": ""})
        self.assertEqual(self.leftovers(), [])

    def test_a_leftover_lock_of_a_finished_process_is_taken_over(self):
        lock = bp.ProfilesLock(self.ctx.workspace.locks_dir, bp.LOCK_NAME, now=self.ctx.now)
        lock.acquire()                                                                # 이 잠금을 쥔 채 '프로그램이 죽은' 것처럼 풀지 않는다
        with mock.patch("chanceblog_desktop.service.lock.process_alive", return_value=False):
            saved = bp.save_slot(self.ctx, "naver_a", form(), expected_version=self.snap().version, wait=1.0)
        self.assertEqual(saved.kind, "saved")
        self.assertEqual(self.leftovers(), [])

    def test_a_lock_held_by_a_live_process_is_never_taken_over(self):
        lock = bp.ProfilesLock(self.ctx.workspace.locks_dir, bp.LOCK_NAME, now=self.ctx.now)
        lock.acquire()
        self.addCleanup(lock.release)
        before = self.tree()
        with mock.patch("chanceblog_desktop.service.lock.process_alive", return_value=True):
            code = code_of(bp.save_slot, self.ctx, "naver_a", form(), expected_version=self.snap().version, wait=0.2)
        self.assertEqual(code, "TOPIC_STORE_LOCKED")
        self.assertEqual({name: data for name, data in self.tree().items() if name.startswith("topic_engine")}, {name: data for name, data in before.items() if name.startswith("topic_engine")})

    def test_two_real_processes_saving_different_slots_in_turn_lose_nothing(self):
        child = Path(__file__).resolve().parent / "blog_profiles_race_child.py"
        env = dict(os.environ, PYTHONPATH=str(ROOT / "src"), PYTHONUTF8="1")
        count = 6
        procs = [subprocess.Popen([sys.executable, "-X", "utf8", str(child), str(self.tmp), slot, str(count)], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
                 for slot in ("naver_a", "naver_b")]
        outputs = [proc.communicate(timeout=240) for proc in procs]
        for proc, (_out, err) in zip(procs, outputs, strict=True):
            self.assertEqual(proc.returncode, 0, err[-400:])
        by_key = {p.key: p for p in tf.load_profiles(self.paths).value}
        self.assertEqual((by_key["naver_a"].alias, by_key["naver_b"].alias), (f"a-{count}", f"b-{count}"), "두 프로세스의 마지막 값이 모두 남았다")
        self.assertEqual(self.leftovers(), [])
        self.assertEqual(len(tf.load_profiles(self.paths).value), 5)


# ---- 소스·실제 값 ----------------------------------------------------------------------------------------------------------------------
class SourceRulesTest(unittest.TestCase):
    SERVICE = ROOT / "src" / "chanceblog_desktop" / "service" / "blog_profiles.py"
    REAL_VALUES = ("ssae" + "ssace", "shine" + "5652", "스마트" + "프라이싱", "스마트" + "초이스", "실전" + "노트", "디지털" + "찬스", "생활가전" + " 선택", "생활 선택" + " 가이드", "AI 서비스" + " 활용", "프로그램 개발" + " 기록")

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
                    inside.setdefault(function.name, 0)
                    inside[function.name] += 1
        self.assertEqual(inside, {"_backup": 1, "_undo_backup": 1, "_restore": 2, "_commit": 1})

    def test_no_real_blog_name_or_id_is_written_anywhere_in_the_repository(self):
        skip = {".git", "vendor", "__pycache__", ".venv"}
        found = []
        for path in ROOT.rglob("*"):
            if not path.is_file() or (set(path.relative_to(ROOT).parts) & skip) or path.suffix not in {".md", ".py", ".txt", ".json", ".yml", ".yaml", ".toml", ".example"}:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            found += [f"{path.relative_to(ROOT).as_posix()}: {value[:2]}…" for value in self.REAL_VALUES if value in text]
        self.assertEqual(found, [], "실제 블로그 이름·아이디는 사용자 데이터에만 둔다(저장소에는 가짜 이름뿐)")

    def test_the_color_presets_and_the_easy_names_exist_in_the_service_wording(self):
        self.assertEqual(channels.COLOR_PRESETS, ("warm_lifestyle", "cool_technology"))
        self.assertEqual(set(wording.COLOR_PRESET_KO), set(channels.COLOR_PRESETS))
        self.assertEqual(set(wording.TAG_KO), {"small_appliance", "pc_peripheral", "lodging_travel", "ai_service", "pc_parts", "work_automation"})
        self.assertEqual(set(wording.LANGUAGE_KO), set(channels.LANGUAGES))


if __name__ == "__main__":
    unittest.main()
