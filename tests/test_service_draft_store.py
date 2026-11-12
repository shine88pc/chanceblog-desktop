"""저장한 초안 서비스(`service/draft_store.py`) 시험 — 진짜 임시 폴더의 글 보관함(`chanceblog.db`)과 진짜 서비스 함수로 확인한다(PySide6 없이 돈다, 네트워크·실제 비밀 없이).

지키는 것:
  1) **저장 → 새 프로세스 → 목록·불러오기 → 저장 당시와 글자까지 같다**(제목·본문·키워드·태그·카테고리·요약·선택 입력·만든 초안). 줄 끝·이모지·결합 글자·널 글자·10만 자 포함.
  2) **원자성**: 커밋이 실패하거나(디스크 가득) 쓰는 도중 예외가 나거나 프로세스가 죽어도 이전에 저장한 판이 그대로이고 부분 기록이 없다. 두 프로세스가 동시에 저장해도 모두 남는다.
  3) **저장 직전 비밀 모양 검사**: 여섯 종류 × 다섯 칸(제목·본문·키워드·태그·요약 — 그 밖의 칸도) 모두 저장을 거절하고 보관함 파일을 만들거나 바꾸지 않으며, 위치와 종류만 알리고 찾은 글은 어디에도 다시 나오지 않는다.
     **'무시하고 저장' 길이 없다**(함수 서명이 정해진 인자뿐이고 소스 어디에도 그런 문구가 없다).
  4) 손상·읽기 전용·잠김·쓸 수 없는 폴더는 쉬운 안내(오류 코드)로 멈추고 파일을 덮어쓰지 않는다. 한도(300편·칸 크기)·충돌(`expected_revision`)·지우기(확인·직전 사본)·읽기 전용 읽기.
  5) 글 보관함 백업 → 되돌리기 뒤에도 저장한 초안이 같다. 서비스 소스에 네트워크·하위 프로세스·새 시계가 없다.
시험 입력의 키 모양은 `scan_samples` 가 실행할 때 조각을 이어 붙여 만든다(소스에 완성된 키가 없다).
"""
import ast
import re
import inspect
import json
import os
import sqlite3
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import scan_samples as SS  # noqa: E402
import service_support as ss  # noqa: E402
from test_service_draft_engine import engine_candidate  # noqa: E402
from test_ui_candidates_service import World  # noqa: E402

from chanceblog_desktop.content import saved_draft as sd  # noqa: E402
from chanceblog_desktop.content.store import Store  # noqa: E402
from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.security import scan  # noqa: E402
from chanceblog_desktop.service import blog_profiles, draft_engine, projects  # noqa: E402
from chanceblog_desktop.service import draft_store as ds  # noqa: E402

SERVICE = ROOT / "src" / "chanceblog_desktop" / "service" / "draft_store.py"
CHILD = Path(__file__).resolve().parent / "draft_store_child.py"
EMOJI = chr(0x1F600)
NFD = "e" + chr(0x0301)
SAVE_PARAMETERS = ["ctx", "title", "body", "core_keywords", "sub_keywords", "tags", "category", "summary", "candidate_id", "topic", "blog", "post_type_choice", "post_type", "options", "base", "draft_id",
                   "expected_revision"]


def values(**more):
    found = dict(title="겨울철 실내 습도 관리", body="첫 문단입니다.\n\n둘째 문단입니다.", core_keywords=("습도 관리",), sub_keywords=("가습기", "곰팡이"), tags=("#습도", "#겨울"), category="생활 정보",
                 summary="한 줄 요약입니다.", candidate_id="cand-1", topic="겨울철 실내 습도 관리 방법", blog="naver_a", post_type="정보형")
    found.update(more)
    return found


def base_of():
    return sd.BaseDraft.build("만든 제목", ["만든 제목", "후보 둘", "후보 셋"], "만든 본문\n둘째 줄", ["확인 권장 하나"], "generic", None)


def raising(call, *args, **kwargs):
    with unittest.TestCase().assertRaises(AppError) as caught:
        call(*args, **kwargs)
    return caught.exception


def child(*arguments, check=True):
    done = subprocess.run([sys.executable, "-X", "utf8", "-I", str(CHILD), *map(str, arguments)], capture_output=True, text=True, encoding="utf-8", timeout=120, cwd=str(ROOT))
    if check and done.returncode != 0:
        raise AssertionError(f"하위 프로세스 실패({done.returncode}): {done.stderr[-400:]}")
    return done


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.ctx = ss.make_ctx(tmp.name)
        self.root = self.ctx.workspace.root

    def save(self, **more):
        return ds.save_draft(self.ctx, **values(**more))

    def rows(self):
        """보관함의 `drafts` 표 전체(번호 순) — 다른 프로세스·다른 연결로 읽는다."""
        path = self.ctx.workspace.store_path
        if not path.exists():
            return None
        with sqlite3.connect(str(path)) as connection:
            return connection.execute("SELECT project_id, text, saved_at FROM drafts ORDER BY project_id").fetchall()

    def database_bytes(self):
        path = self.ctx.workspace.store_path
        return path.read_bytes() if path.exists() else None

    def tree(self):
        return ss.tree_snapshot(self.tmp)


# ---- 1) 저장 → 목록 → 불러오기 ---------------------------------------------------------------------------------------------------------------
class SaveLoadTest(Base):
    def test_a_new_draft_is_saved_listed_and_loaded_with_every_field(self):
        saved = self.save(options={"message": "전하고 싶은 말", "urls": "https://example.invalid/a"}, base=base_of(), post_type_choice="비교형")
        self.assertRegex(saved.draft_id, r"^dd-[0-9a-f]{20}$")
        self.assertEqual((saved.revision, saved.created_at, saved.updated_at), (1, self.ctx.stamp(), self.ctx.stamp()))
        loaded = ds.load_draft(self.ctx, saved.draft_id)
        self.assertEqual(loaded, saved)
        self.assertEqual(loaded.title, "겨울철 실내 습도 관리")
        self.assertEqual(loaded.core_keywords, ("습도 관리",))
        self.assertEqual(loaded.sub_keywords, ("가습기", "곰팡이"))
        self.assertEqual(loaded.tags, ("#습도", "#겨울"))
        self.assertEqual((loaded.category, loaded.summary, loaded.blog, loaded.post_type, loaded.post_type_choice), ("생활 정보", "한 줄 요약입니다.", "naver_a", "정보형", "비교형"))
        self.assertEqual(loaded.options_dict(), {"message": "전하고 싶은 말", "urls": "https://example.invalid/a"})
        self.assertEqual(loaded.base, base_of())
        self.assertEqual((loaded.candidate_id, loaded.topic, loaded.generator), ("cand-1", "겨울철 실내 습도 관리 방법", sd.GENERATOR))
        listing = ds.list_drafts(self.ctx)
        self.assertEqual([entry.draft_id for entry in listing.entries], [saved.draft_id])
        entry = listing.entries[0]
        self.assertEqual((entry.title, entry.topic, entry.blog, entry.revision, entry.updated_at), (saved.title, saved.topic, "naver_a", 1, saved.updated_at))
        self.assertEqual(entry.chars, len("".join(saved.body.split())))
        self.assertEqual(listing.unreadable, ())

    def test_the_draft_lives_in_the_existing_drafts_table_so_the_store_backup_carries_it(self):
        saved = self.save()
        with Store.open(self.ctx.workspace.store_path, migrate=False) as store:
            self.assertEqual(store.schema_version, 2, "표를 새로 만들지 않는다(구조 판 그대로)")
            row = store.load_draft(saved.draft_id)
        self.assertEqual(row.project_id, saved.draft_id)
        self.assertEqual(sd.SavedDraft.from_text(row.text, saved.draft_id), saved)
        self.assertEqual(row.saved_at, self.ctx.stamp())

    def test_saving_again_updates_the_same_draft_and_counts_the_saves(self):
        first = self.save()
        self.ctx.clock.advance(minutes=5)
        second = ds.save_draft(self.ctx, **values(title="고친 제목", body="고친 본문"), draft_id=first.draft_id, expected_revision=1)
        self.assertEqual((second.draft_id, second.revision, second.created_at), (first.draft_id, 2, first.created_at))
        self.assertGreater(second.updated_at, first.updated_at)
        self.ctx.clock.advance(minutes=5)
        third = ds.save_draft(self.ctx, **values(title="다시 고친 제목", body="다시 고친 본문"), draft_id=first.draft_id, expected_revision=2)
        self.assertEqual(third.revision, 3)
        self.assertEqual([entry.title for entry in ds.list_drafts(self.ctx).entries], ["다시 고친 제목"])
        self.assertEqual(len(self.rows()), 1)

    def test_saving_the_same_content_again_writes_nothing(self):
        saved = self.save(base=base_of())
        before = self.database_bytes()
        self.ctx.clock.advance(minutes=5)
        again = ds.save_draft(self.ctx, **values(base=base_of()), draft_id=saved.draft_id, expected_revision=1)
        self.assertEqual(again, saved)
        self.assertEqual(self.database_bytes(), before)

    def test_the_list_is_newest_first_and_ties_go_by_number(self):
        first = self.save(title="가")
        self.ctx.clock.advance(minutes=1)
        second = self.save(title="나")
        self.ctx.clock.advance(minutes=1)
        third = self.save(title="다")
        self.assertEqual([entry.title for entry in ds.list_drafts(self.ctx).entries], ["다", "나", "가"])
        ds.save_draft(self.ctx, **values(title="가 고침"), draft_id=first.draft_id, expected_revision=1)
        self.ctx.clock.advance(minutes=1)
        ds.save_draft(self.ctx, **values(title="가 또 고침"), draft_id=first.draft_id, expected_revision=2)
        self.assertEqual([entry.title for entry in ds.list_drafts(self.ctx).entries], ["가 또 고침", "다", "나"])
        self.assertEqual({second.draft_id, third.draft_id} <= {entry.draft_id for entry in ds.list_drafts(self.ctx).entries}, True)

    def test_without_any_store_file_the_list_is_empty_and_no_file_is_made(self):
        before = self.tree()
        self.assertEqual(ds.list_drafts(self.ctx), ds.DraftListing(()))
        self.assertEqual(ds.list_drafts(self.ctx).total, 0)
        self.assertEqual(self.tree(), before)
        self.assertFalse(self.ctx.workspace.store_path.exists())

    def test_loading_or_deleting_a_draft_that_is_not_there_is_a_not_found_error(self):
        self.assertEqual(raising(ds.load_draft, self.ctx, "dd-" + "0" * 20).code, "CONTENT_NOT_FOUND")
        self.save()
        self.assertEqual(raising(ds.load_draft, self.ctx, "dd-" + "0" * 20).code, "CONTENT_NOT_FOUND")
        self.assertEqual(raising(ds.delete_draft, self.ctx, "dd-" + "0" * 20, confirmed=True).code, "CONTENT_NOT_FOUND")

    def test_a_number_that_is_not_the_shape_is_refused_everywhere(self):
        for bad in ("", "x", "dd-1", "../x", None, 5):
            with self.subTest(bad=bad):
                self.assertEqual(raising(ds.load_draft, self.ctx, bad).code, "CONTENT_INVALID")
                self.assertEqual(raising(ds.delete_draft, self.ctx, bad, confirmed=True).code, "CONTENT_INVALID")
                if bad is not None:
                    self.assertEqual(raising(ds.save_draft, self.ctx, **values(), draft_id=bad).code, "CONTENT_INVALID")

    def test_other_rows_of_the_drafts_table_are_not_ours_and_stay_untouched(self):
        saved = self.save()
        with Store.open(self.ctx.workspace.store_path) as store:
            store.save_draft("legacy-autosave", "옛 자동 저장 글", now=self.ctx.stamp())
            store.save_draft("dd-" + "a" * 20, '{"kind":"other"}', now=self.ctx.stamp())
        listing = ds.list_drafts(self.ctx)
        self.assertEqual([entry.draft_id for entry in listing.entries], [saved.draft_id])
        self.assertEqual(listing.unreadable, (("dd-" + "a" * 20, "DRAFT_CORRUPT"),))
        with Store.open(self.ctx.workspace.store_path, migrate=False) as store:
            self.assertEqual(store.load_draft("legacy-autosave").text, "옛 자동 저장 글")

    def test_a_save_never_touches_the_projects_or_candidates_or_settings(self):
        project = projects.new_project(self.ctx, "옛 글 제목", ss.ko_text())
        settings_before = self.ctx.workspace.settings_path.read_bytes() if self.ctx.workspace.settings_path.exists() else None
        self.save()
        self.assertEqual([row.project_id for row in projects.list_projects(self.ctx)], [project.project_id])
        self.assertEqual(self.ctx.workspace.settings_path.read_bytes() if self.ctx.workspace.settings_path.exists() else None, settings_before)
        self.assertEqual({path.name for path in self.root.iterdir()}, {"chanceblog.db", "settings.json"} if settings_before is not None else {"chanceblog.db"})

    def test_the_time_comes_from_the_context_clock_not_the_real_clock(self):
        saved = self.save()
        self.assertEqual(saved.created_at, "2026-11-02T01:30:12Z")
        with mock.patch("time.time", side_effect=AssertionError("시계를 읽었다")):
            self.save(title="다른 글")

    def test_invalid_arguments_are_refused_before_anything_is_written(self):
        before = self.tree()
        self.assertEqual(raising(ds.save_draft, self.ctx, **values(title=5)).code, "CONTENT_INVALID")
        self.assertEqual(raising(ds.save_draft, self.ctx, **values(body=None)).code, "CONTENT_INVALID")
        self.assertEqual(raising(ds.save_draft, self.ctx, **values(blog="naver_c")).code, "CONTENT_INVALID")
        self.assertEqual(raising(ds.save_draft, self.ctx, **values(), expected_revision=1).code, "CONTENT_INVALID")
        self.assertEqual(raising(ds.save_draft, self.ctx, **values(title="가" * (sd.MAX_TITLE_CHARS + 1))).code, "DRAFT_LIMIT")
        self.assertEqual(self.tree(), before)
        self.assertFalse(self.ctx.workspace.store_path.exists())


# ---- 글자 그대로 -----------------------------------------------------------------------------------------------------------------------------
class ExactTextTest(Base):
    def cases(self):
        yield "줄 끝 섞임", "가\r\n나\n다\r라\r\r\n마\n\r바", "제목\r\n끝"
        yield "이모지와 결합 글자", "본문 " + EMOJI * 4 + " " + NFD + chr(0x00E9), "제목 " + EMOJI + chr(0x1F468) + chr(0x200D) + chr(0x1F469)
        yield "널 글자·서로게이트·BOM", chr(0) + chr(0xD800) + "a" + chr(0xDFFF) + chr(0xFEFF) + chr(0x2028), "  " + chr(0) + "  "
        yield "앞뒤 공백", "  앞뒤 공백  \n\n  ", "  제목  "
        yield "10만 자", ("가나다 abc " + EMOJI + "\r\n") * 10000, "제목"

    def test_title_and_body_come_back_to_the_character_after_a_save_and_a_load(self):
        for name, body, title in self.cases():
            with self.subTest(case=name):
                body = body[:100_000] if name == "10만 자" else body
                saved = self.save(title=title, body=body, candidate_id=f"c-{len(name)}")
                loaded = ds.load_draft(self.ctx, saved.draft_id)
                self.assertEqual((loaded.title, loaded.body), (title, body))

    def test_the_stored_row_is_ascii_and_a_fresh_connection_reads_the_same_values(self):
        saved = self.save(title="제목 " + EMOJI, body="본문\r\n" + chr(0) + "끝")
        text = next(row[1] for row in self.rows() if row[0] == saved.draft_id)
        self.assertTrue(text.isascii())
        again = sd.SavedDraft.from_text(text, saved.draft_id)
        self.assertEqual((again.title, again.body), (saved.title, saved.body))

    def test_edited_fields_are_never_normalized_stripped_or_reordered(self):
        saved = self.save(core_keywords=(" 가 ", "나"), sub_keywords=("", "다"), tags=("#태그", " #태그 "), category="  카테고리 ", summary="요약\n두 줄", topic=NFD)
        loaded = ds.load_draft(self.ctx, saved.draft_id)
        self.assertEqual((loaded.core_keywords, loaded.sub_keywords, loaded.tags, loaded.category, loaded.summary, loaded.topic), ((" 가 ", "나"), ("", "다"), ("#태그", " #태그 "), "  카테고리 ", "요약\n두 줄", NFD))


# ---- 새 프로세스 ----------------------------------------------------------------------------------------------------------------------------
class NewProcessTest(Base):
    def expected(self, draft):
        return {"draft_id": draft.draft_id, "revision": draft.revision, "title": draft.title, "body": draft.body, "core_keywords": list(draft.core_keywords), "sub_keywords": list(draft.sub_keywords),
                "tags": list(draft.tags), "category": draft.category, "summary": draft.summary, "candidate_id": draft.candidate_id, "topic": draft.topic, "blog": draft.blog, "post_type": draft.post_type,
                "options": draft.options_dict(), "created_at": draft.created_at, "updated_at": draft.updated_at, "base": None if draft.base is None else draft.base.to_dict()}

    def test_a_new_process_reads_exactly_what_this_one_saved(self):
        body = ("가나다 abc " + EMOJI + "\r\n" + NFD) * 2000
        saved = self.save(body=body[:100_000], title="제목 " + EMOJI + "\r\n", options={"message": "m\nn"}, base=base_of())
        done = child("dump", self.root, saved.draft_id)
        self.assertEqual(json.loads(done.stdout), self.expected(saved))
        self.assertEqual(done.stdout.strip(), json.dumps(self.expected(saved), ensure_ascii=True))

    def test_a_new_process_lists_every_saved_draft(self):
        first, second = self.save(title="가"), self.save(title="나", body="다른 본문")
        listed = json.loads(child("list", self.root).stdout)
        self.assertEqual(sorted(listed), sorted([[first.draft_id, "가"], [second.draft_id, "나"]]))

    def test_a_save_by_a_new_process_is_read_back_here(self):
        arguments = self.tmp / "args.json"
        arguments.write_text(json.dumps(values(title="다른 프로세스가 저장", body="본문\r\n" + EMOJI)), encoding="utf-8")
        draft_id = child("save", self.root, arguments).stdout.strip()
        loaded = ds.load_draft(self.ctx, draft_id)
        self.assertEqual((loaded.title, loaded.body), ("다른 프로세스가 저장", "본문\r\n" + EMOJI))

    def test_the_draft_survives_the_data_folder_being_moved_and_the_store_reopened(self):
        saved = self.save()
        other = ss.make_ctx(self.tmp / "other")
        other.workspace.root.mkdir(parents=True, exist_ok=True)
        other.workspace.store_path.write_bytes(self.database_bytes())
        self.assertEqual(ds.load_draft(other, saved.draft_id), saved)


# ---- 2) 원자성 ------------------------------------------------------------------------------------------------------------------------------
class FailingDb:
    """연결 앞에 끼우는 대리 — 정해진 문장에서 SQLite 오류를 낸다(디스크 가득·입출력 오류 흉내). 나머지는 그대로 넘긴다."""

    def __init__(self, real, fail_on, message):
        self.real, self.fail_on, self.message = real, fail_on, message

    def execute(self, sql, *args):
        if self.fail_on(sql):
            raise sqlite3.OperationalError(self.message)
        return self.real.execute(sql, *args)

    def __getattr__(self, name):
        return getattr(self.real, name)


def failing_open(fail_on, message, **options):
    original = Store.open.__func__

    def open_(cls, path, **keywords):
        store = original(cls, path, **{**keywords, **options})
        store._db = FailingDb(store._db, fail_on, message)
        return store

    return mock.patch.object(Store, "open", classmethod(open_))


class AtomicityTest(Base):
    def check_old_save_is_intact(self, saved, rows_before, *, journal_gone=True):
        self.assertEqual(self.rows(), rows_before)
        self.assertEqual(ds.load_draft(self.ctx, saved.draft_id), saved)
        connection = sqlite3.connect(str(self.ctx.workspace.store_path))
        try:
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        finally:
            connection.close()
        if journal_gone:
            self.assertFalse(Path(str(self.ctx.workspace.store_path) + "-journal").exists(), "되돌려진 트랜잭션의 저널이 남지 않는다")

    def test_a_commit_that_fails_for_a_full_disk_leaves_the_earlier_save_and_no_partial_row(self):
        saved = self.save(title="먼저 저장한 글")
        rows_before = self.rows()
        with failing_open(lambda sql: sql.strip().upper() == "COMMIT", "database or disk is full"):
            error = raising(ds.save_draft, self.ctx, **values(title="디스크가 가득 찼을 때 쓰는 글"), draft_id=saved.draft_id, expected_revision=1)
            new_error = raising(ds.save_draft, self.ctx, **values(title="새 글", body="새 본문"))
        self.assertEqual((error.code, new_error.code), ("DISK_FULL", "DISK_FULL"))
        self.assertTrue(error.rendered().message)
        self.check_old_save_is_intact(saved, rows_before)

    def test_an_error_in_the_middle_of_the_transaction_leaves_the_earlier_save(self):
        saved = self.save(title="먼저 저장한 글")
        rows_before = self.rows()
        with failing_open(lambda sql: sql.lstrip().upper().startswith("INSERT INTO DRAFTS"), "disk I/O error"):
            error = raising(ds.save_draft, self.ctx, **values(title="쓰다 멈춘 글"), draft_id=saved.draft_id, expected_revision=1)
        self.assertEqual(error.code, "FILE_WRITE_FAILED")
        self.check_old_save_is_intact(saved, rows_before)

    def test_a_process_that_dies_inside_a_write_transaction_leaves_the_earlier_save_after_reopening(self):
        saved = self.save(title="먼저 저장한 글")
        rows_before = self.rows()
        done = child("crash", self.root, saved.draft_id, check=False)
        self.assertEqual(done.returncode, 3)
        self.check_old_save_is_intact(saved, rows_before, journal_gone=False)        # 쓰기 도중 죽은 프로세스의 저널은 다음 쓰기가 정리한다 — 글은 그전에도 이전 판 그대로다
        self.save(title="그 뒤에도 저장된다", body="새 본문")
        self.assertEqual(len(ds.list_drafts(self.ctx).entries), 2)
        self.assertEqual(ds.load_draft(self.ctx, saved.draft_id), saved)
        connection = sqlite3.connect(str(self.ctx.workspace.store_path))
        try:
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        finally:
            connection.close()

    def test_a_failed_save_does_not_stop_the_next_one(self):
        with failing_open(lambda sql: sql.strip().upper() == "COMMIT", "database or disk is full"):
            self.assertEqual(raising(ds.save_draft, self.ctx, **values()).code, "DISK_FULL")
        saved = self.save()
        self.assertEqual(ds.load_draft(self.ctx, saved.draft_id), saved)

    def test_two_processes_saving_at_once_keep_every_draft_and_a_sound_file(self):
        signal = self.tmp / "go"
        self.ctx.workspace.root.mkdir(parents=True, exist_ok=True)
        ds.save_draft(self.ctx, **values(title="처음 저장"))
        processes = [subprocess.Popen([sys.executable, "-X", "utf8", "-I", str(CHILD), "many", str(self.root), prefix, "12", str(signal)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                      encoding="utf-8", cwd=str(ROOT)) for prefix in ("가", "나")]
        signal.write_text("go", encoding="utf-8")
        outputs = []
        for process in processes:
            out, err = process.communicate(timeout=120)
            self.assertEqual(process.returncode, 0, err[-400:])
            outputs.append(json.loads(out))
        titles = sorted(entry.title for entry in ds.list_drafts(self.ctx).entries)
        self.assertEqual(titles, sorted(["처음 저장"] + [f"{prefix}-{number}" for prefix in ("가", "나") for number in range(12)]))
        with sqlite3.connect(str(self.ctx.workspace.store_path)) as connection:
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        self.assertEqual(len(outputs[0]) + len(outputs[1]), 24)

    def test_threads_saving_at_once_through_separate_connections_all_land(self):
        self.ctx.workspace.root.mkdir(parents=True, exist_ok=True)
        errors = []

        def work(number):
            try:
                ds.save_draft(self.ctx, **values(title=f"스레드 {number}", body=f"본문 {number}"))
            except Exception as error:      # noqa: BLE001 — 시험이 실패를 모아서 본다
                errors.append(error)

        threads = [threading.Thread(target=work, args=(number,)) for number in range(10)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(60)
        self.assertEqual(errors, [])
        self.assertEqual(len(ds.list_drafts(self.ctx).entries), 10)


# ---- 같은 초안을 동시에 저장(D-369) ---------------------------------------------------------------------------------------------------------
class SameDraftRaceTest(Base):
    """같은 초안을 두 프로세스가 동시에 저장한다 — 확인(저장 횟수 비교·한도)과 쓰기가 **한 트랜잭션**이라 어느 저장도 조용히 사라지지 않는다(D-369). 읽고 확인한 뒤 따로 쓰던 예전 구현은
    두 프로세스가 같은 판을 읽고 둘 다 쓰면 판이 한 번 덜 올랐다(독립 검증이 92번 성공에 최종 84 로 쟀다). 앞의 둘은 시간에 기대는 압박 시험이고, 뒤의 둘은 시간에 기대지 않는 시험이다."""

    COUNT = 30

    def race(self, how):
        first = self.save(title="처음 저장")
        signal = self.tmp / "go"
        processes = [subprocess.Popen([sys.executable, "-X", "utf8", "-I", str(CHILD), "same", str(self.root), first.draft_id, str(self.COUNT), str(signal), how, prefix],
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", cwd=str(ROOT)) for prefix in ("가", "나")]
        signal.write_text("go", encoding="utf-8")
        results = []
        for process in processes:
            out, err = process.communicate(timeout=180)
            self.assertEqual(process.returncode, 0, err[-400:])
            results.append(json.loads(out.strip().splitlines()[-1]))
        return first, results

    def test_saves_without_an_expected_revision_all_count_and_the_file_stays_sound(self):
        first, results = self.race("free")
        done = sum(item["done"] for item in results)
        self.assertEqual((done, sum(item["conflicts"] for item in results)), (2 * self.COUNT, 0))
        self.assertEqual(ds.load_draft(self.ctx, first.draft_id).revision, 1 + done, "성공한 저장마다 저장 횟수가 하나씩 올랐다 — 갱신이 조용히 사라지지 않았다")
        self.assertEqual(len(ds.list_drafts(self.ctx).entries), 1)
        with sqlite3.connect(str(self.ctx.workspace.store_path)) as connection:
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    def test_saves_with_an_expected_revision_either_land_or_report_a_conflict_and_none_vanishes(self):
        first, results = self.race("expect")
        done, conflicts = (sum(item[key] for item in results) for key in ("done", "conflicts"))
        self.assertEqual(done + conflicts, 2 * self.COUNT, "저장 하나하나가 성공하거나 충돌로 알려졌다")
        self.assertGreaterEqual(done, 1)
        self.assertEqual(ds.load_draft(self.ctx, first.draft_id).revision, 1 + done, "성공했다고 한 저장이 하나도 조용히 사라지지 않았다")
        with sqlite3.connect(str(self.ctx.workspace.store_path)) as connection:
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    def test_the_check_runs_while_the_write_lock_is_held(self):
        """결정적 시험 — 저장한 기록을 읽어 풀고 저장 횟수를 견주는 그 순간에 다른 연결의 쓰기는 들어오지 못한다(`STORE_LOCKED`). 읽기가 잠금 밖이면 그 틈에서 서로의 갱신을 덮어쓴다."""
        saved = self.save(title="먼저 저장한 글")
        other = Store.open(self.ctx.workspace.store_path, busy_seconds=0.05)
        self.addCleanup(other.close)
        real = sd.SavedDraft.from_text
        seen = []

        def spy(cls, text, draft_id):
            with self.assertRaises(AppError) as caught:
                other.update_draft(draft_id, lambda stored, count: "끼어든 글", prefix=sd.ID_PREFIX)
            seen.append(caught.exception.code)
            return real(text, draft_id)

        with mock.patch.object(sd.SavedDraft, "from_text", classmethod(spy)):
            updated = ds.save_draft(self.ctx, **values(title="고친 제목"), draft_id=saved.draft_id, expected_revision=1)
        self.assertEqual(seen, ["STORE_LOCKED"])
        self.assertEqual((updated.revision, ds.load_draft(self.ctx, saved.draft_id).title), (2, "고친 제목"))

    def test_the_conflict_is_decided_on_the_text_in_the_file_at_the_moment_of_the_write(self):
        """결정적 시험 — 이 저장이 쓰는 순간의 파일 기준으로 충돌을 가른다. 불러온 뒤 다른 곳에서 저장했으면(저장 횟수가 올랐으면) 낡은 화면의 저장은 `STORE_CONFLICT` 이고 파일은 그대로다."""
        saved = self.save(title="먼저 저장한 글")
        ds.save_draft(self.ctx, **values(title="다른 창에서 고침"), draft_id=saved.draft_id, expected_revision=1)
        rows = self.rows()
        error = raising(ds.save_draft, self.ctx, **values(title="낡은 화면에서 고침"), draft_id=saved.draft_id, expected_revision=1)
        self.assertEqual(error.code, "STORE_CONFLICT")
        self.assertEqual(self.rows(), rows)


# ---- 쓰다가 죽어 저널이 남은 보관함을 읽기(D-370) ------------------------------------------------------------------------------------------
class HotJournalTest(Base):
    """앱이 **큰** 저장을 하다 갑자기 꺼져 저널이 남은 보관함 — 예전에는 읽기 전용으로만 여는 목록·불러오기·열기가 `STORE_RECOVERY_PENDING` 으로 멈췄고 '다시 읽기' 로도 풀리지 않았다(쓰는 열기가 정리할 때까지).
    이제 읽는 길이 그때만 보통 열기로 한 번 정리한 뒤 읽는다(D-370) — 저장해 둔 초안은 그대로다."""

    def crashed(self):
        first = self.save(title="먼저 저장한 글")
        second = self.save(title="두 번째 글", body="둘째 본문")
        rows_before = self.rows()
        done = child("crash_big", self.root, first.draft_id, check=False)
        self.assertEqual(done.returncode, 3, done.stderr[-300:])
        journal = Path(str(self.ctx.workspace.store_path) + "-journal")
        if not (journal.exists() and journal.stat().st_size > 0):
            self.skipTest("이 환경에서는 큰 저장 도중 죽어도 저널이 남지 않는다 — D-370 의 상황을 만들 수 없다")
        try:
            Store.open(self.ctx.workspace.store_path, migrate=False).close()
        except AppError as error:
            self.assertEqual(error.code, "STORE_RECOVERY_PENDING", "읽기 전용 열기는 저널을 정리하지 못해 이 오류로 멈춘다 — 이 시험의 전제")
        else:
            self.skipTest("이 환경의 읽기 전용 열기는 저널이 남아도 읽는다 — D-370 의 상황이 아니다")
        return first, second, rows_before, journal

    def check_recovered(self, rows_before, journal):
        self.assertFalse(journal.exists() and journal.stat().st_size > 0, "읽은 뒤 저널이 정리됐다")
        self.assertEqual(self.rows(), rows_before, "저장해 둔 초안은 한 칸도 바뀌지 않았다")
        with sqlite3.connect(str(self.ctx.workspace.store_path)) as connection:
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    def test_the_list_after_a_crash_in_a_big_save_shows_the_saved_drafts(self):
        first, second, rows_before, journal = self.crashed()
        listing = ds.list_drafts(self.ctx)
        self.assertEqual(sorted(entry.title for entry in listing.entries), ["두 번째 글", "먼저 저장한 글"])
        self.assertEqual(listing.unreadable, ())
        self.check_recovered(rows_before, journal)

    def test_loading_a_draft_after_a_crash_in_a_big_save_gives_the_saved_text(self):
        first, second, rows_before, journal = self.crashed()
        self.assertEqual(ds.load_draft(self.ctx, first.draft_id), first)
        self.check_recovered(rows_before, journal)

    def test_opening_a_draft_after_a_crash_in_a_big_save_works(self):
        first, second, rows_before, journal = self.crashed()
        opened = ds.open_saved(self.ctx, second.draft_id)
        self.assertEqual(opened.draft, second)
        self.check_recovered(rows_before, journal)

    def test_a_store_without_a_leftover_journal_is_still_read_without_being_opened_for_writing(self):
        """정상 보관함의 읽기는 예전처럼 읽기 전용이다 — 쓰는 열기는 저널이 남았을 때만(D-370)."""
        self.save(title="저장한 글")
        opened = []
        real = Store.open

        def spy(path, **kwargs):
            opened.append(kwargs.get("migrate", True))
            return real(path, **kwargs)

        with mock.patch.object(Store, "open", staticmethod(spy)):
            ds.list_drafts(self.ctx)
            ds.load_draft(self.ctx, ds.list_drafts(self.ctx).entries[0].draft_id)
        self.assertEqual(opened, [False, False, False])

    def test_another_open_failure_is_not_turned_into_a_write_open(self):
        """저널이 남은 때가 아닌 다른 실패(깨진 파일 등)는 그대로 알린다 — 읽는 길이 쓰는 열기로 바뀌지 않는다."""
        self.save(title="저장한 글")
        path = self.ctx.workspace.store_path
        path.write_bytes(b"not a database" * 200)
        before = path.read_bytes()
        opened = []
        real = Store.open

        def spy(p, **kwargs):
            opened.append(kwargs.get("migrate", True))
            return real(p, **kwargs)

        with mock.patch.object(Store, "open", staticmethod(spy)):
            error = raising(ds.list_drafts, self.ctx)
        self.assertEqual(error.code, "STORE_CORRUPT")
        self.assertEqual(opened, [False])
        self.assertEqual(path.read_bytes(), before)


# ---- 3) 저장 직전 비밀 모양 검사 ------------------------------------------------------------------------------------------------------------
FIELDS = (("제목", "title", False), ("본문", "body", False), ("핵심 키워드", "core_keywords", True), ("보조 키워드", "sub_keywords", True), ("태그", "tags", True), ("카테고리", "category", False),
          ("요약", "summary", False), ("후보 주제", "topic", False))


BASE_FIELDS = (("만든 초안 제목", "title"), ("만든 초안 제목 후보", "titles"), ("만든 초안 본문", "body"), ("만든 초안 확인 권장", "checks"), ("만든 초안 바꾼 형식", "replaced"))


def base_with(field, line):
    """키 모양 한 줄을 만든 초안의 칸 하나에만 넣은 만든 초안."""
    title, titles, body, checks, replaced = "만든 제목", ["만든 제목", "후보 둘"], "만든 본문", ["확인 하나"], None
    if field == "title":
        title = "앞 " + line
    elif field == "titles":
        titles = ["후보 하나", line]
    elif field == "body":
        body = "만든 본문\n" + line
    elif field == "checks":
        checks = ["확인 하나", line]
    else:
        replaced = ["후기형", "앞 " + line]
    return sd.BaseDraft.build(title, titles, body, checks, "generic", replaced)


class SecretCheckTest(Base):
    def put(self, key, line, label, listed):
        return {key: (line,) if listed else "앞글 " + line + " 뒷글"}

    def shown_everywhere(self, error):
        pieces = [str(error), repr(error), error.rendered().message, error.rendered().action, error.rendered().retry_text, error.detail, repr(error.slots), error.advice(), ds.places_text(error.findings),
                  repr(error.findings), repr(error.args)]
        return " | ".join(pieces)

    def test_every_kind_in_every_field_stops_the_save_before_the_store_is_even_opened(self):
        for kind in SS.KINDS:
            token, line = SS.sample(kind)
            for label, key, listed in FIELDS:
                with self.subTest(kind=kind, field=label):
                    before = self.tree()
                    error = raising(ds.save_draft, self.ctx, **values(**self.put(key, line, label, listed)))
                    self.assertIsInstance(error, ds.DraftSecretError)
                    self.assertEqual(error.code, "DRAFT_SECRET_FOUND")
                    self.assertEqual([item.kind for item in error.findings], [kind])
                    self.assertEqual(error.findings[0].where, label)
                    self.assertEqual(self.tree(), before, "보관함 파일을 만들거나 바꾸지 않았다")
                    self.assertFalse(self.ctx.workspace.store_path.exists())
                    self.assertFalse(SS.leaked(self.shown_everywhere(error), token), "찾은 글이 어디에도 다시 나오지 않는다")
                    self.assertIn(label, error.advice())
                    self.assertIn("자동으로 지우거나 바꾸지 않아요", error.advice())

    def test_the_advice_names_only_the_place_and_the_kind(self):
        token, line = SS.sample("github_token")
        error = raising(ds.save_draft, self.ctx, **values(body="첫 줄\n둘째 줄\n" + line))
        self.assertEqual([(item.where, item.line, item.kind) for item in error.findings], [("본문", 3, "github_token")])
        self.assertIn("본문에서 1건(GitHub 토큰 1) — 3번째 줄", error.advice())
        self.assertEqual(ds.places_text(error.findings), "본문 3번째 줄")
        self.assertIn("본문 3번째 줄", error.rendered().message)

    def test_every_place_is_reported_when_several_fields_have_one(self):
        google, github = SS.sample("google_api_key")[1], SS.sample("github_token")[1]
        error = raising(ds.save_draft, self.ctx, **values(title="제목 " + google, body="본문\n" + github, tags=(github,), summary=google))
        self.assertEqual(sorted({item.where for item in error.findings}), ["본문", "요약", "제목", "태그"])
        self.assertEqual(ds.places_text(error.findings).count("·") + 1, 3)
        self.assertIn("외 1곳", ds.places_text(error.findings))

    def test_an_option_input_with_a_key_stops_the_save_and_names_the_option_in_korean(self):
        token, line = SS.sample("aws_access_key")
        error = raising(ds.save_draft, self.ctx, **values(options={"experience": "써 보니 " + line}))
        self.assertIn("선택 입력(실제 사용 경험)", [item.where for item in error.findings])
        self.assertFalse(SS.leaked(self.shown_everywhere(error), token))

    def test_a_key_that_stays_in_a_saved_draft_blocks_the_next_save_and_the_old_text_stays(self):
        saved = self.save()
        before = self.rows()
        line = SS.sample("bearer_token")[1]
        error = raising(ds.save_draft, self.ctx, **values(body="고친 본문\n" + line), draft_id=saved.draft_id, expected_revision=1)
        self.assertEqual(error.code, "DRAFT_SECRET_FOUND")
        self.assertEqual(self.rows(), before)
        self.assertEqual(ds.load_draft(self.ctx, saved.draft_id), saved)

    def test_a_key_only_in_the_made_draft_stops_the_save_and_only_the_place_is_told(self):
        """예전에는 만든 초안(base)에서만 찾으면 그 칸만 조용히 빼고 '저장했어요' 로 끝났다 — 운영자 결정(발견 시 저장 중지·자동 삭제 금지·위치와 유형만)에 어긋나 뒤집었다(D-368)."""
        token, line = SS.sample("google_api_key")
        base = sd.BaseDraft.build("만든 제목", ["만든 제목"], "만든 본문 " + line, ["확인"], "generic", None)
        before = self.tree()
        error = raising(ds.save_draft, self.ctx, **values(base=base))
        self.assertIsInstance(error, ds.DraftSecretError)
        self.assertEqual([(item.where, item.line, item.kind) for item in error.findings], [("만든 초안 본문", 1, "google_api_key")])
        self.assertEqual(ds.places_text(error.findings), "만든 초안 본문 1번째 줄")
        self.assertEqual(self.tree(), before)
        self.assertFalse(self.ctx.workspace.store_path.exists(), "보관함 파일을 만들지도 않았다")
        self.assertFalse(SS.leaked(self.shown_everywhere(error), token))
        self.assertIn(sd.MADE_DRAFT_ADVICE, error.advice())
        self.assertNotIn("해당 줄을 만든 초안 본문에서", error.advice())

    def test_every_kind_in_every_made_draft_field_stops_the_save_and_the_store_stays_byte_for_byte(self):
        existing = self.save(title="먼저 저장한 글")
        before_rows, before_bytes, before_tree = self.rows(), self.database_bytes(), self.tree()
        for kind in SS.KINDS:
            token, line = SS.sample(kind)
            for label, field in BASE_FIELDS:
                with self.subTest(kind=kind, field=label):
                    error = raising(ds.save_draft, self.ctx, **values(title="저장하려던 글", base=base_with(field, line)))
                    self.assertIsInstance(error, ds.DraftSecretError)
                    self.assertEqual(error.code, "DRAFT_SECRET_FOUND")
                    self.assertEqual([item.kind for item in error.findings], [kind])
                    self.assertEqual(error.findings[0].where, label)
                    self.assertEqual((self.rows(), self.database_bytes(), self.tree()), (before_rows, before_bytes, before_tree), "보관함은 한 바이트도 바뀌지 않았다")
                    self.assertFalse(SS.leaked(self.shown_everywhere(error), token))
                    self.assertIn(label, error.advice())
                    self.assertTrue(error.advice().endswith(sd.MADE_DRAFT_ADVICE))
        self.assertEqual(ds.load_draft(self.ctx, existing.draft_id), existing)

    def test_every_kind_in_every_made_draft_field_never_creates_the_store_in_an_empty_folder(self):
        before = self.tree()
        for kind in SS.KINDS:
            token, line = SS.sample(kind)
            for label, field in BASE_FIELDS:
                with self.subTest(kind=kind, field=label):
                    raising(ds.save_draft, self.ctx, **values(base=base_with(field, line)))
                    self.assertFalse(self.ctx.workspace.store_path.exists())
                    self.assertEqual(self.tree(), before)

    def test_a_key_shape_in_the_candidate_number_or_the_made_drafts_field_is_found_and_never_stored(self):
        """검사 대상이 아니었던 칸 둘(후보 번호·만든 초안의 분야 — D-368): 서비스를 직접 부르면 이름 규칙(영문·숫자·`._-`)에 맞는 키 모양이 들어갈 수 있었다. 이제 찾으면 저장하지 않고, 칸의 이름 규칙에 안 맞는 모양은 칸 검사가 먼저 거절한다."""
        def attempt(make, token):
            try:                                              # 칸의 이름 규칙은 만들 때(`BaseDraft.build`)나 저장할 때(`SavedDraft.build`) 먼저 거른다
                return raising(ds.save_draft, self.ctx, **make(token))
            except AppError as error:
                return error

        fitted = {"후보 번호": [], "만든 초안 분야": []}
        before = self.tree()
        for kind in SS.KINDS:
            token = SS.sample(kind)[0]
            for label, make, rule in (("후보 번호", lambda text: values(candidate_id=text), re.compile(r"[A-Za-z0-9_-]{1,64}")),
                                      ("만든 초안 분야", lambda text: values(base=sd.BaseDraft.build("만든 제목", ["만든 제목"], "만든 본문", [], text, None)), re.compile(r"[A-Za-z0-9._-]{0,40}"))):
                with self.subTest(kind=kind, field=label):
                    error = attempt(make, token)
                    self.assertFalse(SS.leaked(self.shown_everywhere(error) if isinstance(error, ds.DraftSecretError) else repr(error.slots) + str(error) + error.detail, token))
                    if rule.fullmatch(token) is None:
                        self.assertEqual(error.code, "CONTENT_INVALID", "칸의 이름 규칙에 안 맞는 모양은 칸 검사가 먼저 거절한다")
                    else:
                        fitted[label].append(kind)
                        self.assertIsInstance(error, ds.DraftSecretError)
                        self.assertEqual([(item.where, item.kind) for item in error.findings], [(label, kind)])
                    self.assertFalse(self.ctx.workspace.store_path.exists(), "어느 쪽이든 보관함에 아무것도 쓰지 않았다")
                    self.assertEqual(self.tree(), before)
        self.assertEqual(sorted(fitted["후보 번호"]), ["aws_access_key", "github_token", "google_api_key"], "후보 번호 칸에서 검사까지 가는 종류")
        self.assertEqual(sorted(fitted["만든 초안 분야"]), ["aws_access_key", "github_token", "google_api_key", "oauth_token"], "분야 칸에서 검사까지 가는 종류")

    def test_clean_text_with_words_like_token_or_key_is_saved(self):
        saved = self.save(body="이 글은 API 키와 토큰이라는 낱말, Bearer 라는 낱말, AKIA 로 시작하는 예시 설명을 담지만 모양을 다 갖춘 키는 없어요.\n해시 " + "a" * 40)
        self.assertTrue(ds.load_draft(self.ctx, saved.draft_id).body.startswith("이 글은 API 키와 토큰이라는 낱말"))

    def test_the_save_function_has_no_way_to_skip_the_check(self):
        parameters = list(inspect.signature(ds.save_draft).parameters)
        self.assertEqual(parameters, SAVE_PARAMETERS, "새 인자가 생기면(검사를 건너뛰는 길일 수 있어) 이 시험이 먼저 빨개진다")
        for name in parameters:
            self.assertFalse(any(word in name for word in ("force", "ignore", "skip", "bypass", "override", "unsafe", "allow", "yes", "confirm", "check", "scan", "secret")), name)
        self.assertEqual(len(inspect.signature(ds.DraftSecretError).parameters), 1)

    PHRASES = ("무시하고 저장", "그래도 저장", "검사 건너뛰", "검사를 건너", "그대로 저장하기", "경고 무시하고")
    NEGATION = re.compile(r"[\s'\u2019\u201d\"\u300d]*(?:은|는|도|이|가)?\s*없")

    @classmethod
    def offers(cls, text):
        """글에 '검사를 건너뛰고 저장' 을 **권하는** 말이 있나(있으면 그 말). 바로 뒤에 '없' 이 오는 말(\"'무시하고 저장' 도 없습니다\")은 권하는 것이 아니라 없다고 알리는 것이라 센다 아니다."""
        for phrase in cls.PHRASES:
            start = 0
            while True:
                index = text.find(phrase, start)
                if index < 0:
                    break
                if cls.NEGATION.match(text[index + len(phrase):index + len(phrase) + 12]) is None:
                    return phrase
                start = index + len(phrase)
        return None

    def test_no_source_file_offers_a_save_that_ignores_the_check(self):
        """화면 글·오류 문구·값에 검사를 건너뛰고 저장하는 말이 없다 — 설명 글(독스트링)은 '없다' 고 적을 수 있어 빼고, 오류 문구가 '무시하고 저장 도 없습니다' 처럼 없다고 알리는 말은 권하는 말이 아니라 센다 아니다(D-374)."""
        found = []
        for path in (ROOT / "src").rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            docstrings = {id(node.body[0].value) for node in ast.walk(tree) if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef)) and node.body
                          and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant)}
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings and self.offers(node.value):
                    found.append((path.name, node.value[:30]))
        self.assertEqual(found, [], "화면 글·오류 문구·값에 검사를 건너뛰고 저장하는 말이 없다(설명 글(독스트링)은 '없다' 고 적을 수 있어 뺀다)")

    def test_the_offer_finder_catches_an_offer_and_lets_a_denial_pass(self):
        """위 시험의 눈이 정말 권하는 말은 잡고 없다고 알리는 말은 놓아주는지 — 합성 글로 확인한다."""
        for offer in ("무시하고 저장", "경고가 나와도 무시하고 저장 하기", "그래도 저장 할래요", "검사를 건너뛰고 저장", "'무시하고 저장' 도 있습니다", "무시하고 저장 없이는 안 돼요 무시하고 저장"):
            with self.subTest(offer=offer):
                self.assertIsNotNone(self.offers(offer))
        for denial in ("앱은 글을 자동으로 지우거나 바꾸지 않고 '무시하고 저장' 도 없습니다. 실제 키였다면 폐기합니다.", "무시하고 저장은 없다", "그래도 저장 은 없어요", "무시하고 저장 없음", "그래도 저장이 없어요", "그대로 저장하기가 없습니다"):
            with self.subTest(denial=denial):
                self.assertIsNone(self.offers(denial))

    def test_the_findings_object_has_no_text_in_any_representation(self):
        token, line = SS.sample("pem_private_key")
        error = raising(ds.save_draft, self.ctx, **values(body=line))
        import dataclasses
        import pickle
        item = error.findings[0]
        shown = repr(item) + str(item) + repr(dataclasses.asdict(item)) + repr(pickle.dumps(item)) + repr(item.__reduce_ex__(2))
        self.assertFalse(SS.leaked(shown, token))


# ---- 4) 손상·읽기 전용·잠김·쓸 수 없는 폴더 ---------------------------------------------------------------------------------------------------
class BrokenStoreTest(Base):
    def test_a_damaged_store_file_stops_the_save_and_the_list_with_a_corrupt_error_and_is_not_overwritten(self):
        self.root.mkdir(parents=True, exist_ok=True)
        damaged = b"not a database " * 200
        self.ctx.workspace.store_path.write_bytes(damaged)
        for call in (lambda: ds.save_draft(self.ctx, **values()), lambda: ds.list_drafts(self.ctx), lambda: ds.load_draft(self.ctx, "dd-" + "0" * 20),
                     lambda: ds.delete_draft(self.ctx, "dd-" + "0" * 20, confirmed=True)):
            error = raising(call)
            self.assertEqual(error.code, "STORE_CORRUPT")
            self.assertTrue(error.rendered().message and error.rendered().action)
        self.assertEqual(self.ctx.workspace.store_path.read_bytes(), damaged)

    def test_a_read_only_store_file_stops_the_save_with_a_write_error_and_reading_still_works(self):
        saved = self.save()
        path = self.ctx.workspace.store_path
        os.chmod(path, stat.S_IREAD)
        self.addCleanup(os.chmod, path, stat.S_IREAD | stat.S_IWRITE)
        if os.access(path, os.W_OK):
            self.skipTest("이 계정은 읽기 전용 표시를 무시한다(관리자 권한)")
        before = path.read_bytes()
        error = raising(ds.save_draft, self.ctx, **values(title="쓸 수 없는 곳"), draft_id=saved.draft_id, expected_revision=1)
        self.assertIn(error.code, ("FILE_WRITE_FAILED", "MIGRATION_BLOCKED"))
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(ds.load_draft(self.ctx, saved.draft_id), saved)
        self.assertEqual(len(ds.list_drafts(self.ctx).entries), 1)

    def test_a_store_locked_by_another_connection_gives_a_locked_error_and_nothing_is_lost(self):
        saved = self.save()
        rows_before = self.rows()
        holder = sqlite3.connect(str(self.ctx.workspace.store_path), isolation_level=None)
        self.addCleanup(holder.close)
        holder.execute("BEGIN IMMEDIATE")
        with failing_open(lambda sql: False, "", busy_seconds=0.2):
            error = raising(ds.save_draft, self.ctx, **values(title="잠겨 있을 때"), draft_id=saved.draft_id, expected_revision=1)
        self.assertEqual(error.code, "STORE_LOCKED")
        holder.execute("ROLLBACK")
        self.assertEqual(self.rows(), rows_before)
        self.save(title="잠금이 풀린 뒤")
        self.assertEqual(len(ds.list_drafts(self.ctx).entries), 2)

    def test_a_data_folder_that_cannot_be_made_gives_a_write_error_and_other_reads_stay_empty(self):
        shutil.rmtree(self.root)
        self.root.write_bytes(b"a file where the data folder should be")
        error = raising(ds.save_draft, self.ctx, **values())
        self.assertEqual(error.code, "FILE_WRITE_FAILED")
        self.assertTrue(error.rendered().message)
        self.assertEqual(ds.list_drafts(self.ctx), ds.DraftListing(()))
        self.assertEqual(self.root.read_bytes(), b"a file where the data folder should be")

    def test_a_store_made_by_a_newer_program_is_not_written(self):
        saved = self.save()
        with sqlite3.connect(str(self.ctx.workspace.store_path)) as connection:
            connection.execute("PRAGMA user_version = 99")
        before = self.database_bytes()
        error = raising(ds.save_draft, self.ctx, **values(title="더 새로운 파일"), draft_id=saved.draft_id, expected_revision=1)
        self.assertEqual(error.code, "STORE_VERSION_UNSUPPORTED")
        self.assertEqual(self.database_bytes(), before)

    def test_one_unreadable_draft_does_not_hide_the_others_and_can_be_deleted(self):
        good = self.save(title="멀쩡한 초안")
        bad_id = "dd-" + "b" * 20
        with Store.open(self.ctx.workspace.store_path) as store:
            store.save_draft(bad_id, "깨진 기록 {", now=self.ctx.stamp())
        listing = ds.list_drafts(self.ctx)
        self.assertEqual([entry.draft_id for entry in listing.entries], [good.draft_id])
        self.assertEqual(listing.unreadable, ((bad_id, "DRAFT_CORRUPT"),))
        self.assertEqual(listing.total, 2)
        self.assertEqual(raising(ds.load_draft, self.ctx, bad_id).code, "DRAFT_CORRUPT")
        self.assertEqual(ds.load_draft(self.ctx, good.draft_id), good)
        ds.delete_draft(self.ctx, bad_id, confirmed=True)
        self.assertEqual(ds.list_drafts(self.ctx).unreadable, ())
        self.assertEqual([entry.draft_id for entry in ds.list_drafts(self.ctx).entries], [good.draft_id])

    def test_saving_over_a_corrupt_record_of_the_same_number_is_refused_not_overwritten(self):
        saved = self.save()
        with Store.open(self.ctx.workspace.store_path) as store:
            store.save_draft(saved.draft_id, "깨졌다", now=self.ctx.stamp())
        error = raising(ds.save_draft, self.ctx, **values(title="덮어쓰기"), draft_id=saved.draft_id)
        self.assertEqual(error.code, "DRAFT_CORRUPT")
        self.assertEqual(self.rows()[0][1], "깨졌다")


# ---- 한도·충돌 ------------------------------------------------------------------------------------------------------------------------------
class LimitAndConflictTest(Base):
    def fill(self, count):
        self.ctx.workspace.root.mkdir(parents=True, exist_ok=True)
        with Store.open(self.ctx.workspace.store_path) as store:
            for number in range(count):
                draft_id = sd.make_draft_id(self.ctx.stamp(), "", "naver_a", f"제목 {number}", "본문")
                record = sd.SavedDraft.build(draft_id=draft_id, revision=1, created_at=self.ctx.stamp(), updated_at=self.ctx.stamp(), title=f"제목 {number}", body="본문", blog="naver_a", post_type="정보형")
                store.save_draft(draft_id, record.to_text(), now=self.ctx.stamp())

    def test_the_three_hundredth_draft_is_saved_and_the_next_new_one_is_refused_but_updates_still_work(self):
        self.fill(sd.MAX_SAVED - 1)
        last = self.save(title="삼백 번째")
        self.assertEqual(len(ds.list_drafts(self.ctx).entries), sd.MAX_SAVED)
        error = raising(ds.save_draft, self.ctx, **values(title="삼백한 번째", body="다른 본문"))
        self.assertEqual(error.code, "DRAFT_LIMIT")
        self.assertIn(str(sd.MAX_SAVED), error.rendered().message)
        self.assertEqual(len(ds.list_drafts(self.ctx).entries), sd.MAX_SAVED, "앱이 오래된 초안을 지우지 않는다")
        updated = ds.save_draft(self.ctx, **values(title="삼백 번째 고침"), draft_id=last.draft_id, expected_revision=1)
        self.assertEqual(updated.revision, 2)

    def test_the_cap_holds_for_any_new_row_even_one_made_with_a_number_given_directly(self):
        """예전에는 한도를 '번호 없이 새로 만드는' 저장에만 걸었다 — 없는 `dd-` 번호를 직접 주면 305편까지 들어갔다(D-371). 이제 새 행을 만드는 저장은 번호를 주었든 아니든 같은 한도다."""
        self.fill(sd.MAX_SAVED)
        rows_before = self.rows()
        for expected in (None, 1):
            with self.subTest(expected=expected):
                error = raising(ds.save_draft, self.ctx, **values(title="번호를 직접 준 새 글"), draft_id="dd-" + "f" * 20, expected_revision=expected)
                self.assertEqual(error.code, "DRAFT_LIMIT")
        self.assertEqual(self.rows(), rows_before)
        self.assertEqual(len(ds.list_drafts(self.ctx).entries), sd.MAX_SAVED)

    def test_a_numbered_save_that_makes_the_last_allowed_row_is_accepted_and_updates_at_the_cap_still_work(self):
        self.fill(sd.MAX_SAVED - 1)
        again = ds.save_draft(self.ctx, **values(title="299 뒤에 번호를 직접 준 글"), draft_id="dd-" + "e" * 20, expected_revision=1)
        self.assertEqual((again.revision, len(ds.list_drafts(self.ctx).entries)), (2, sd.MAX_SAVED))
        ds.save_draft(self.ctx, **values(title="이미 있는 글을 고침"), draft_id=again.draft_id, expected_revision=2)
        self.assertEqual(len(ds.list_drafts(self.ctx).entries), sd.MAX_SAVED, "있는 글을 고치는 저장은 한도에 걸리지 않는다")

    def test_a_save_too_big_for_one_storage_cell_is_refused_before_the_store_file_is_even_created(self):
        """이모지 때문에 JSON 이 보관함 한 칸(2,000,000자)을 넘는 글 — 칸마다의 한도는 모두 지켰지만 합치면 크다. 빈 폴더에 보관함 파일도 폴더도 만들지 않는다(저장 직전 `to_text()` 확인을 지우면 파일이 생긴다 — 독립 검증의 변이 V16)."""
        base = sd.BaseDraft.build("t", ["t"], EMOJI * sd.MAX_BASE_BODY_CHARS, [], "generic", None)

        def names():
            root = self.ctx.workspace.root
            return sorted(path.name for path in root.iterdir()) if root.exists() else None

        before_tree, before_names = self.tree(), names()
        error = raising(ds.save_draft, self.ctx, **values(body=EMOJI * sd.MAX_BODY_CHARS, base=base))
        self.assertEqual(error.code, "DRAFT_LIMIT")
        self.assertFalse(self.ctx.workspace.store_path.exists())
        self.assertEqual((self.tree(), names()), (before_tree, before_names), "파일도 폴더도 새로 생기지 않았다")

    def test_a_save_too_big_for_one_storage_cell_leaves_an_existing_store_byte_for_byte(self):
        self.save(title="먼저 저장한 글")
        before_bytes, before_tree = self.database_bytes(), self.tree()
        base = sd.BaseDraft.build("t", ["t"], EMOJI * sd.MAX_BASE_BODY_CHARS, [], "generic", None)
        self.assertEqual(raising(ds.save_draft, self.ctx, **values(title="큰 글", body=EMOJI * sd.MAX_BODY_CHARS, base=base)).code, "DRAFT_LIMIT")
        self.assertEqual((self.database_bytes(), self.tree()), (before_bytes, before_tree))

    def test_a_save_made_from_a_stale_screen_does_not_overwrite_a_newer_one(self):
        first = self.save()
        ds.save_draft(self.ctx, **values(title="다른 창에서 고침"), draft_id=first.draft_id, expected_revision=1)
        before = self.rows()
        error = raising(ds.save_draft, self.ctx, **values(title="낡은 화면에서 고침"), draft_id=first.draft_id, expected_revision=1)
        self.assertEqual(error.code, "STORE_CONFLICT")
        self.assertIn(sd.short_id(first.draft_id), error.rendered().message)
        self.assertEqual(self.rows(), before)
        again = ds.save_draft(self.ctx, **values(title="최신 판 위에 고침"), draft_id=first.draft_id, expected_revision=2)
        self.assertEqual(again.revision, 3)

    def test_without_an_expected_revision_the_last_save_wins(self):
        first = self.save()
        ds.save_draft(self.ctx, **values(title="둘째"), draft_id=first.draft_id)
        last = ds.save_draft(self.ctx, **values(title="셋째"), draft_id=first.draft_id)
        self.assertEqual((last.revision, ds.load_draft(self.ctx, first.draft_id).title), (3, "셋째"))

    def test_a_draft_deleted_elsewhere_is_made_again_so_the_edit_is_not_lost(self):
        first = self.save()
        ds.delete_draft(self.ctx, first.draft_id, confirmed=True)
        again = ds.save_draft(self.ctx, **values(title="지워진 뒤에 고친 글"), draft_id=first.draft_id, expected_revision=1)
        self.assertEqual((again.draft_id, again.revision, again.title), (first.draft_id, 2, "지워진 뒤에 고친 글"))
        self.assertEqual(ds.load_draft(self.ctx, first.draft_id).title, "지워진 뒤에 고친 글")

    def test_a_bad_expected_revision_is_refused(self):
        first = self.save()
        for bad in (0, -1, True, "1", 1.0):
            with self.subTest(bad=bad):
                self.assertEqual(raising(ds.save_draft, self.ctx, **values(), draft_id=first.draft_id, expected_revision=bad).code, "CONTENT_INVALID")


# ---- 지우기·백업·되돌리기 --------------------------------------------------------------------------------------------------------------------
class DeleteAndBackupTest(Base):
    def test_delete_needs_the_confirmation_and_changes_nothing_without_it(self):
        saved = self.save()
        before = self.tree()
        for bad in (False, None, 1, "yes", "True"):
            with self.subTest(confirmed=bad):
                self.assertEqual(raising(ds.delete_draft, self.ctx, saved.draft_id, confirmed=bad).code, "CONFIRMATION_REQUIRED")
        self.assertEqual(self.tree(), before)
        self.assertEqual(len(self.rows()), 1)

    def test_a_confirmed_delete_makes_the_before_delete_copy_first_and_removes_only_that_draft(self):
        keep, gone = self.save(title="남길 초안"), self.save(title="지울 초안", body="다른 본문")
        copy = ds.delete_draft(self.ctx, gone.draft_id, confirmed=True)
        self.assertEqual(copy.parent, self.ctx.workspace.backups_dir / "before-delete")
        self.assertTrue(copy.is_file())
        self.assertEqual([entry.draft_id for entry in ds.list_drafts(self.ctx).entries], [keep.draft_id])
        with Store.open(copy, migrate=False) as backup:
            self.assertEqual(sd.SavedDraft.from_text(backup.load_draft(gone.draft_id).text, gone.draft_id), gone, "지우기 직전 사본에 지운 초안이 그대로 있다")

    def test_a_delete_that_cannot_make_its_copy_deletes_nothing(self):
        saved = self.save()
        with mock.patch.object(Store, "backup", side_effect=AppError("BACKUP_FAILED", detail="시험")):
            self.assertEqual(raising(ds.delete_draft, self.ctx, saved.draft_id, confirmed=True).code, "BACKUP_FAILED")
        self.assertEqual([entry.draft_id for entry in ds.list_drafts(self.ctx).entries], [saved.draft_id])

    def test_two_deletes_in_the_same_second_keep_both_copies(self):
        first, second = self.save(title="가"), self.save(title="나", body="다른")
        one = ds.delete_draft(self.ctx, first.draft_id, confirmed=True)
        two = ds.delete_draft(self.ctx, second.draft_id, confirmed=True)
        self.assertNotEqual(one, two)
        self.assertTrue(one.is_file() and two.is_file())

    def test_the_store_backup_and_restore_carry_the_saved_drafts_unchanged(self):
        saved = self.save(body="본문\r\n" + EMOJI, base=base_of(), options={"message": "m"})
        copy = projects.backup_store(self.ctx)
        ds.save_draft(self.ctx, **values(title="백업 뒤에 고침"), draft_id=saved.draft_id, expected_revision=1)
        extra = self.save(title="백업 뒤에 새로 저장", body="새 본문")
        self.assertEqual(len(ds.list_drafts(self.ctx).entries), 2)
        projects.restore_store(self.ctx, copy, confirmed=True)
        self.assertEqual([entry.draft_id for entry in ds.list_drafts(self.ctx).entries], [saved.draft_id])
        self.assertEqual(ds.load_draft(self.ctx, saved.draft_id), saved)
        self.assertEqual(raising(ds.load_draft, self.ctx, extra.draft_id).code, "CONTENT_NOT_FOUND")

    def test_a_backup_copied_to_another_data_folder_restores_the_same_drafts(self):
        saved = self.save(body="본문\r\n" + chr(0) + NFD)
        copy = projects.backup_store(self.ctx)
        other = ss.make_ctx(self.tmp / "other")
        projects.restore_store(other, copy, confirmed=True)
        self.assertEqual(ds.load_draft(other, saved.draft_id), saved)


# ---- 읽기는 아무것도 바꾸지 않는다 ------------------------------------------------------------------------------------------------------------
class ReadOnlyReadTest(Base):
    def test_listing_loading_and_opening_change_no_byte_of_the_data_folder(self):
        saved = self.save(candidate_id="cand-x")
        before = self.tree()
        ds.list_drafts(self.ctx)
        ds.load_draft(self.ctx, saved.draft_id)
        ds.open_saved(self.ctx, saved.draft_id)
        self.assertEqual(self.tree(), before)

    def test_reading_an_old_structure_store_neither_upgrades_nor_copies_it(self):
        saved = self.save()
        with sqlite3.connect(str(self.ctx.workspace.store_path)) as connection:
            connection.execute("DROP TABLE candidates")
            connection.execute("PRAGMA user_version = 1")
        before = self.tree()
        self.assertEqual([entry.draft_id for entry in ds.list_drafts(self.ctx).entries], [saved.draft_id])
        self.assertEqual(ds.load_draft(self.ctx, saved.draft_id), saved)
        self.assertEqual(self.tree(), before)


# ---- 다시 열기(블로그 정보·이어진 후보) ----------------------------------------------------------------------------------------------------------
class OpenSavedTest(unittest.TestCase):
    def setUp(self):
        self.world = World(self)
        self.ctx = self.world.ctx

    def register(self, key="naver_a", name="예시 블로그", ref="myblogid"):
        snapshot = blog_profiles.read_snapshot(self.ctx)
        blog_profiles.save_slot(self.ctx, key, {"display_name": name, "blog_ref": ref}, expected_version=snapshot.version)

    def save(self, **more):
        return ds.save_draft(self.ctx, **values(**more))

    def test_an_open_draft_whose_candidate_still_exists_reports_found_and_the_profile_names(self):
        engine = engine_candidate(1, "naver_a")
        self.world.add(engine)
        self.register()
        opened = ds.open_saved(self.ctx, self.save(candidate_id=engine.candidate_id).draft_id)
        self.assertEqual(opened.candidate, "found")
        self.assertFalse(opened.context_problem)
        self.assertEqual(dict(opened.context.blog_names)["naver_a"], "예시 블로그")
        self.assertEqual((opened.context.blog_url, opened.context.address, opened.context.channel_found), ("https://blog.naver.com/myblogid", "channel", True))

    def test_a_deleted_candidate_still_opens_and_says_the_candidate_is_gone(self):
        engine = engine_candidate(1, "naver_a")
        self.world.add(engine)
        saved = self.save(candidate_id=engine.candidate_id)
        self.world.paths.database.unlink()
        opened = ds.open_saved(self.ctx, saved.draft_id)
        self.assertEqual(opened.candidate, "missing")
        self.assertEqual(opened.draft, saved)

    def test_a_draft_without_a_candidate_says_none(self):
        self.assertEqual(ds.open_saved(self.ctx, self.save(candidate_id="").draft_id).candidate, "none")

    def test_an_unreadable_candidate_store_says_unknown_and_the_draft_still_opens(self):
        saved = self.save(candidate_id="cand-1")
        self.world.paths.folder.mkdir(parents=True, exist_ok=True)
        self.world.paths.database.write_bytes(b"not a database " * 100)
        opened = ds.open_saved(self.ctx, saved.draft_id)
        self.assertEqual(opened.candidate, "unknown")
        self.assertEqual(opened.draft.title, saved.title)

    def test_an_empty_profile_slot_opens_with_default_names_and_no_address(self):
        opened = ds.open_saved(self.ctx, self.save().draft_id)
        self.assertEqual((opened.context.blog_url, opened.context.address, opened.context.channel_found), ("", "none", False))
        self.assertEqual([key for key, _name in opened.context.blog_names], ["naver_a", "naver_b"])

    def test_a_broken_settings_file_does_not_stop_the_draft_from_opening(self):
        saved = self.save()
        self.ctx.workspace.settings_path.write_text("{not json", encoding="utf-8")
        opened = ds.open_saved(self.ctx, saved.draft_id)
        self.assertTrue(opened.context_problem)
        self.assertEqual((opened.context.blog_url, opened.context.address, opened.context.blog_names), ("", "none", ()))
        self.assertEqual(opened.draft, saved)

    def test_the_old_naver_profile_address_wins_over_the_channel_profile_like_when_the_draft_was_made(self):
        ss.naver_profiles(self.ctx)
        self.register(ref="channelid")
        opened = ds.open_saved(self.ctx, self.save().draft_id)
        self.assertEqual((opened.context.blog_url, opened.context.address, opened.context.profile_found), ("https://blog.naver.com/exampleaaa", "profile", True))

    def test_a_channel_address_that_is_not_a_naver_blog_is_marked_unusable(self):
        self.register(ref="https://example.invalid/myid")
        opened = ds.open_saved(self.ctx, self.save().draft_id)
        self.assertEqual((opened.context.blog_url, opened.context.address), ("", "unusable"))


# ---- 5) 소스 규칙 ---------------------------------------------------------------------------------------------------------------------------
class SourceRulesTest(unittest.TestCase):
    def setUp(self):
        self.tree = ast.parse(SERVICE.read_text(encoding="utf-8"))

    def test_the_service_imports_no_network_process_clock_or_random_module(self):
        names = set()
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                names |= {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                names.add((node.module or "").split(".")[0])
        self.assertFalse(names & {"subprocess", "socket", "urllib", "http", "ssl", "webbrowser", "ctypes", "os", "time", "datetime", "random", "secrets", "uuid", "shutil", "tempfile", "pathlib", "sqlite3"}, names)

    def test_every_write_goes_through_the_store_and_the_service_opens_no_file_itself(self):
        calls = [ast.unparse(node.func) for node in ast.walk(self.tree) if isinstance(node, ast.Call)]
        self.assertEqual(sorted({call for call in calls if call.endswith(("save_draft", "update_draft", "discard_draft", "backup"))}), ["store.backup", "store.discard_draft", "store.update_draft"])
        for call in calls:
            self.assertFalse(any(word in call for word in ("write_text", "write_bytes", "unlink", "mkdir", "rename", "os.replace", "rmtree")) or call in ("open", "os.open"), call)

    def test_the_write_functions_are_exactly_save_and_delete(self):
        writers = sorted({function.name for function in ast.walk(self.tree) if isinstance(function, ast.FunctionDef)
                          for node in ast.walk(function) if isinstance(node, ast.Call) and ast.unparse(node.func) in ("store.update_draft", "store.discard_draft", "store.backup")})
        self.assertEqual(writers, ["delete_draft", "save_draft"])

    def test_the_scanner_runs_before_the_store_is_opened_in_save(self):
        function = next(node for node in ast.walk(self.tree) if isinstance(node, ast.FunctionDef) and node.name == "save_draft")
        lines = {ast.unparse(node.func): node.lineno for node in ast.walk(function) if isinstance(node, ast.Call)}
        self.assertLess(lines["_check_secrets"], lines["ctx.store"], "비밀 모양 검사는 보관함을 열기 전에 한다")
        self.assertIn("scan.scan_fields", {ast.unparse(node.func) for node in ast.walk(next(f for f in ast.walk(self.tree) if isinstance(f, ast.FunctionDef) and f.name == "_check_secrets")) if isinstance(node, ast.Call)})

    def test_no_english_secret_word_in_a_string_of_the_service(self):
        import re
        words = re.compile(r"(?i)\b(api[_ -]?key|secret|token|passw(?:or)?d|credential)s?\b")
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                self.assertIsNone(words.search(node.value), node.value[:40])

    def test_the_scan_api_the_service_calls_exists(self):
        for name in ("scan_fields", "summarize", "describe", "has_secret", "scan_secrets"):
            self.assertTrue(callable(getattr(scan, name)))


if __name__ == "__main__":
    unittest.main()
