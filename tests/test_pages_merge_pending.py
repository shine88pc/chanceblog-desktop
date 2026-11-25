"""'병합 기다리는 중'(`MERGE_PENDING`)과 그 저장 형식 시험(PUBPR P1, 결정 D-740 — 설계서 PT-20·21·28·29, 네트워크·진짜 git 없음).

지키는 것:
  1) 상태 흐름 — `APPROVED → MERGE_PENDING → PUSHED → PUBLISHED`. 병합 확인(`PUSHED`)을 거치지 않고 `MERGE_PENDING → PUBLISHED` 로 바로 가는 길은 없고, 승인 전·올린 뒤·실패에서 `MERGE_PENDING` 으로 가는 길도 없다(PT-20).
  2) 원고를 고쳐도 `MERGE_PENDING` 은 그대로다 — 이미 올라간 것은 과거의 사실이다(PT-21). `COMMITTED`·`PUSHED` 와 같다.
  3) `MERGE_PENDING` 글은 `remote_id` 에 `가지@커밋`(가지 이름은 상수 접두사 + 숫자·16진수뿐) 을 꼭 가진다 — 바꿀 때도, 저장된 것을 읽을 때도 모양을 본다. 이 모양과 git 층의 가지 이름 규칙은 같은 규칙이다.
  4) 옛 데이터를 그대로 읽는다 — `COMMITTED`·`PUSHED` 글과 발행 기록 판 1(칸 여섯)은 새 코드에서도 읽힌다(PT-28).
  5) 보관함 판 2 → 3(PT-29): 표 구조는 그대로이고 판 번호만 오른다 — 판 2 파일은 사본 `.v2.bak` 을 남기고 올라가고, 판 1 파일은 사본 `.v1.bak` 하나만 남기고 한 번에 3 으로 오르며,
     옛 프로그램(판 2)은 판 3 파일을 `STORE_VERSION_UNSUPPORTED` 로 거절하고 파일은 한 바이트도 바뀌지 않는다. 판 3 백업은 옛 프로그램에서 복원되지 않고 판 2 백업은 복원하면 3 으로 오른다. 글 파일(프로젝트 JSON)의 칸 집합은 그대로다.
  6) 발행 기록 판 2 — 칸 `branch` 와 단계 `built`·`branch_pushed` 가 더해지고, 단계와 가지 칸이 맞지 않으면 읽기·쓰기가 거절된다.
"""
import hashlib
import json
import re
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "src"))
import service_support as ss  # noqa: E402
import store_v1  # noqa: E402

from chanceblog_desktop.content import status as st  # noqa: E402
from chanceblog_desktop.content import store as store_module  # noqa: E402
from chanceblog_desktop.content.model import ContentProject, PlatformVariant  # noqa: E402
from chanceblog_desktop.content.store import APPLICATION_ID, SCHEMA_VERSION, Store  # noqa: E402
from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.publish import gitrepo  # noqa: E402
from chanceblog_desktop.service import format as fmt  # noqa: E402
from chanceblog_desktop.service import journal as journal_module  # noqa: E402
from chanceblog_desktop.service.journal import (BRANCH_STAGES, STAGE_BRANCH_PUSHED, STAGE_BUILT, STAGE_COMMITTED, STAGE_PUSHED, Journal, PublishRecord)  # noqa: E402

NOW = "2026-11-25T03:00:00Z"
LATER = "2026-11-25T04:30:00Z"
BRANCH = "desktop/post-20261125-123456-0a1b2c3d"
COMMIT = "c" * 40
REMOTE_ID = f"{BRANCH}@{COMMIT}"
PAGES = "github_pages"


def raises(test, code, callable_, *args, **kwargs):
    with test.assertRaises(AppError) as caught:
        callable_(*args, **kwargs)
    test.assertEqual(caught.exception.code, code, caught.exception.detail)
    return caught.exception


def approved_project(project_id="p1"):
    """승인까지 마친 글(Pages) — 승인한 렌더링이 현재 판과 같다."""
    project = ContentProject.new("주제가 분명한 제목", "본문 첫 문단입니다.\n\n둘째 문단입니다.", [], [], project_id=project_id, now=NOW)
    project.set_rendered(PAGES, "Pages 용 글", now=NOW)
    project.transition(PAGES, st.REVIEW_REQUIRED, now=NOW)
    project.transition(PAGES, st.APPROVED, now=LATER)
    return project


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class StateFlowTest(unittest.TestCase):
    """PT-20 — 상태 흐름과 허용되지 않는 전이."""

    def test_state_flow_approved_to_merge_pending_to_pushed_to_published(self):
        project = approved_project()
        project.transition(PAGES, st.MERGE_PENDING, remote_id=REMOTE_ID, now=LATER)
        variant = project.variant(PAGES)
        self.assertEqual((variant.status, variant.remote_id), (st.MERGE_PENDING, REMOTE_ID))
        project.transition(PAGES, st.PUSHED, remote_id="d" * 40, now=LATER)
        self.assertEqual((variant.status, variant.remote_id), (st.PUSHED, "d" * 40))
        project.transition(PAGES, st.PUBLISHED, published_url="https://example.invalid/posts/2026/11/25/KR-123456/", now=LATER)
        self.assertEqual(variant.status, st.PUBLISHED)

    def test_the_flow_table_has_the_new_state_exactly_where_the_design_puts_it(self):
        flow = st.FLOWS[st.PAGES]
        self.assertEqual(flow[st.APPROVED], (st.COMMITTED, st.MERGE_PENDING, st.REVIEW_REQUIRED, st.PUBLISH_FAILED))
        self.assertEqual(flow[st.MERGE_PENDING], (st.PUSHED, st.PUBLISH_FAILED))
        self.assertEqual(flow[st.COMMITTED], (st.PUSHED, st.PUBLISH_FAILED), "옛 상태는 하나도 바뀌지 않았다")
        self.assertEqual(flow[st.PUSHED], (st.PUBLISHED, st.PUBLISH_FAILED))
        order = list(flow)
        self.assertLess(order.index(st.COMMITTED), order.index(st.MERGE_PENDING))
        self.assertLess(order.index(st.MERGE_PENDING), order.index(st.PUSHED), "화면에 보이는 진행 순서: COMMITTED 다음, PUSHED 앞")
        for family in (st.BLOGGER, st.NAVER):
            self.assertNotIn(st.MERGE_PENDING, st.FLOWS[family], "다른 플랫폼에는 병합을 기다리는 상태가 없다")

    def test_merge_pending_never_goes_straight_to_published_or_back_to_approval(self):
        project = approved_project()
        project.transition(PAGES, st.MERGE_PENDING, remote_id=REMOTE_ID, now=LATER)
        for requested in (st.PUBLISHED, st.APPROVED, st.REVIEW_REQUIRED, st.DRAFT_GENERATED, st.COMMITTED, st.NOT_STARTED, st.MERGE_PENDING):
            with self.subTest(requested=requested):
                exc = raises(self, "STATUS_TRANSITION_INVALID", project.transition, PAGES, requested, published_url="https://example.invalid/x/", now=LATER)
                self.assertEqual(project.variant(PAGES).status, st.MERGE_PENDING, "거절하면 아무것도 바뀌지 않는다")
                self.assertEqual(exc.slots["현재 상태"], st.MERGE_PENDING)

    def test_only_an_approved_post_can_start_waiting_for_a_merge(self):
        for source in (st.NOT_STARTED, st.DRAFT_GENERATED, st.REVIEW_REQUIRED, st.COMMITTED, st.PUSHED, st.PUBLISHED, st.PUBLISH_FAILED):
            with self.subTest(source=source):
                self.assertFalse(st.can_transition(PAGES, source, st.MERGE_PENDING))
        self.assertTrue(st.can_transition(PAGES, st.APPROVED, st.MERGE_PENDING))

    def test_a_failed_or_abandoned_merge_goes_to_failed_and_back_to_review(self):
        project = approved_project()
        project.transition(PAGES, st.MERGE_PENDING, remote_id=REMOTE_ID, now=LATER)
        project.transition(PAGES, st.PUBLISH_FAILED, error_code="PUBLISH_CANCELLED", now=LATER)
        self.assertEqual(project.variant(PAGES).status, st.PUBLISH_FAILED)
        project.transition(PAGES, st.REVIEW_REQUIRED, now=LATER)
        self.assertEqual(project.variant(PAGES).status, st.REVIEW_REQUIRED)

    def test_waiting_for_a_merge_needs_the_branch_at_commit_identifier_and_nothing_else_will_do(self):
        for label, remote_id in {"없음": None, "빈 글": "", "가지만": BRANCH, "커밋만": COMMIT, "짧은 커밋": f"{BRANCH}@{'c' * 39}", "대문자 커밋": f"{BRANCH}@{'C' * 40}", "main": f"main@{COMMIT}",
                                 "다른 접두사": f"ai/claude/post-20261125-123456-0a1b2c3d@{COMMIT}", "제목 조각": f"desktop/post-경제-123456-0a1b2c3d@{COMMIT}", "공백": f"{BRANCH} @{COMMIT}",
                                 "뒤에 줄바꿈": REMOTE_ID + "\n", "긴 글": REMOTE_ID + "x" * 300}.items():
            project = approved_project()
            with self.subTest(label=label):
                raises(self, "CONTENT_INVALID", project.transition, PAGES, st.MERGE_PENDING, remote_id=remote_id, now=LATER)
                self.assertEqual(project.variant(PAGES).status, st.APPROVED, "거절하면 승인 상태 그대로")

    def test_a_stored_merge_pending_post_without_a_good_identifier_is_refused_when_read(self):
        project = approved_project()
        project.transition(PAGES, st.MERGE_PENDING, remote_id=REMOTE_ID, now=LATER)
        data = project.to_dict()
        self.assertEqual(ContentProject.from_dict(data).variant(PAGES).remote_id, REMOTE_ID)
        for label, remote_id in {"없음": None, "모양 틀림": "abc", "main": "main"}.items():
            broken = json.loads(json.dumps(data))
            broken["variants"][PAGES]["remote_id"] = remote_id
            with self.subTest(label=label):
                raises(self, "CONTENT_INVALID", ContentProject.from_dict, broken)

    def test_the_status_has_an_easy_korean_name_and_a_next_step_line(self):
        self.assertEqual(fmt.STATUS_KO[st.MERGE_PENDING], "병합 기다리는 중")
        from chanceblog_desktop.ui.core import post_text
        self.assertEqual(post_text.POST_T["post_status_MERGE_PENDING"], fmt.STATUS_KO[st.MERGE_PENDING], "화면과 명령줄이 같은 낱말을 쓴다")
        variant = PlatformVariant(PAGES, st.MERGE_PENDING)
        self.assertEqual(variant.status, st.MERGE_PENDING)
        view = mock.Mock(project_id="abcdef1234567890", variants=[mock.Mock(platform=PAGES, status=st.MERGE_PENDING)])
        text = "\n".join(fmt.next_step_lines(view))
        self.assertIn("merge-check abcdef12", text)
        self.assertIn("abandon abcdef12 --yes", text)
        self.assertNotIn("main 에 올립니다", text)

    def test_every_status_of_the_flow_has_a_name_and_the_screen_table_has_it_too(self):
        from chanceblog_desktop.ui.core import post_text
        for family in st.FLOWS.values():
            for status in family:
                self.assertIn(status, fmt.STATUS_KO, status)
                self.assertIn(f"post_status_{status}", post_text.POST_T, status)


class EditingTest(unittest.TestCase):
    """PT-21 — 원고를 고쳐도 올라간 것은 과거의 사실이다."""

    def test_merge_pending_is_not_reset_by_editing_the_text(self):
        project = approved_project()
        project.transition(PAGES, st.MERGE_PENDING, remote_id=REMOTE_ID, now=LATER)
        self.assertNotIn(st.MERGE_PENDING, st.RESET_ON_EDIT)
        before = project.revision
        self.assertTrue(project.edit(source_content="본문을 고쳤습니다.", now=LATER))
        self.assertEqual(project.revision, before + 1)
        variant = project.variant(PAGES)
        self.assertEqual((variant.status, variant.remote_id, variant.rendered), (st.MERGE_PENDING, REMOTE_ID, "Pages 용 글"), "상태·식별자·승인한 렌더링이 그대로다")
        self.assertEqual(variant.rendered_revision, before, "승인한 렌더링은 옛 판으로 남는다 — 병합 확인은 이 승인한 글과 견준다")
        again = ContentProject.from_dict(project.to_dict())
        self.assertEqual(again.variant(PAGES).status, st.MERGE_PENDING)

    def test_the_other_states_that_are_reset_still_are(self):
        project = approved_project()
        project.edit(source_content="고쳤다.", now=LATER)
        self.assertEqual(project.variant(PAGES).status, st.DRAFT_GENERATED)
        self.assertEqual(st.RESET_ON_EDIT, {"REVIEW_REQUIRED", "APPROVED", "DRAFT_SAVED", "READY_TO_COPY", "COPY_COMPLETED", "PUBLISH_FAILED"}, "기존 목록은 한 칸도 바뀌지 않았다")


class RemoteIdShapeTest(unittest.TestCase):
    def test_split_remote_id_returns_the_branch_and_the_commit_or_none(self):
        self.assertEqual(st.split_remote_id(REMOTE_ID), (BRANCH, COMMIT))
        for bad in (None, 5, "", "x", BRANCH, REMOTE_ID + "\n", " " + REMOTE_ID, REMOTE_ID.upper()):
            with self.subTest(bad=repr(bad)[:20]):
                self.assertIsNone(st.split_remote_id(bad))

    def test_the_identifier_branch_part_is_the_same_rule_as_the_git_layers_branch_name(self):
        """내용 쪽 식별자 규칙과 git 층의 가지 이름 규칙은 같은 규칙이다 — 한쪽만 고치면 빨개진다."""
        self.assertEqual(st.MERGE_REMOTE_ID.pattern, gitrepo.BRANCH_NAME.pattern + "@[0-9a-f]{40}")
        self.assertTrue(gitrepo.BRANCH_NAME.fullmatch(BRANCH))
        self.assertIsNone(gitrepo.BRANCH_NAME.fullmatch(BRANCH + "\n"))
        self.assertTrue(BRANCH.startswith(gitrepo.BRANCH_PREFIX))
        self.assertLessEqual(len(REMOTE_ID), 200, "기존 식별자 길이 검사(200자·공백 없음)를 지난다")
        self.assertEqual(len(REMOTE_ID), 78)


class LegacyDataTest(unittest.TestCase):
    """PT-28 — 옛 데이터는 새 코드에서도 그대로 읽힌다."""

    def test_legacy_committed_and_pushed_data_still_loads(self):
        for status, extra in ((st.COMMITTED, {}), (st.PUSHED, {"remote_id": "d" * 40})):
            project = approved_project()
            project.transition(PAGES, st.COMMITTED, now=LATER)
            if status == st.PUSHED:
                project.transition(PAGES, st.PUSHED, now=LATER, **extra)
            data = json.loads(json.dumps(project.to_dict()))
            with self.subTest(status=status):
                self.assertEqual(ContentProject.from_dict(data).variant(PAGES).status, status)
                self.assertEqual(data["schema"], 1, "글 파일(프로젝트 JSON)의 판은 바뀌지 않았다")

    def test_the_project_json_keys_did_not_change(self):
        project = approved_project()
        project.transition(PAGES, st.MERGE_PENDING, remote_id=REMOTE_ID, now=LATER)
        data = project.to_dict()
        self.assertEqual(set(data), {"schema", "project_id", "title", "source_content", "references", "assets", "created_at", "updated_at", "revision", "variants"})
        self.assertEqual(set(data["variants"][PAGES]), {"status", "rendered", "rendered_revision", "published_url", "published_at", "remote_id", "error_code"})
        self.assertEqual(data["schema"], 1)

    def test_a_version_one_journal_record_is_read_with_an_empty_branch(self):
        with tempfile.TemporaryDirectory() as tmp:
            record = {"schema": 1, "project_id": "p1", "path": ss.KO_PATH, "commit": "c" * 40, "base": "b" * 40, "stage": "committed"}
            (Path(tmp) / "p1.json").write_text(json.dumps(record), encoding="utf-8")
            found = Journal(tmp).read("p1")
            self.assertEqual(found, PublishRecord("p1", ss.KO_PATH, "c" * 40, "b" * 40, STAGE_COMMITTED, ""))
            self.assertEqual(found.branch, "")
            (Path(tmp) / "p1.json").write_text(json.dumps({**record, "stage": "pushed"}), encoding="utf-8")
            self.assertEqual(Journal(tmp).read("p1").stage, STAGE_PUSHED)


class JournalVersionTwoTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)
        self.journal = Journal(self.folder)

    def raw(self, project_id="p1"):
        return json.loads((self.folder / f"{project_id}.json").read_text(encoding="utf-8"))

    def test_a_branch_record_is_written_with_schema_two_and_the_branch_column_and_read_back(self):
        for stage in BRANCH_STAGES:
            record = PublishRecord("p1", ss.KO_PATH, COMMIT, "b" * 40, stage, BRANCH)
            self.journal.write(record)
            self.assertEqual(self.journal.read("p1"), record)
            self.assertEqual(sorted(self.raw()), ["base", "branch", "commit", "path", "project_id", "schema", "stage"])
            self.assertEqual((self.raw()["schema"], self.raw()["branch"], self.raw()["stage"]), (journal_module.SCHEMA, BRANCH, stage))
        self.assertEqual(journal_module.SCHEMA, 2)
        self.assertEqual(journal_module.STAGES, (STAGE_COMMITTED, STAGE_PUSHED, STAGE_BUILT, STAGE_BRANCH_PUSHED))

    def test_old_style_records_are_written_in_the_new_shape_too_and_still_read(self):
        record = PublishRecord("p1", ss.KO_PATH, COMMIT, "b" * 40, STAGE_PUSHED)
        self.journal.write(record)
        self.assertEqual(self.raw()["schema"], 2)
        self.assertEqual(self.raw()["branch"], "")
        self.assertEqual(self.journal.read("p1"), record)

    def test_the_branch_must_fit_the_stage(self):
        bad = {"가지 단계인데 가지가 비었다": (STAGE_BUILT, ""), "가지 단계인데 가지가 비었다(올림 대기)": (STAGE_BRANCH_PUSHED, ""), "옛 방식 단계에 가지": (STAGE_COMMITTED, BRANCH),
               "모양이 틀린 가지": (STAGE_BUILT, "desktop/post-1"), "main": (STAGE_BRANCH_PUSHED, "main"), "다른 접두사": (STAGE_BUILT, "ai/claude/post-20261125-123456-0a1b2c3d"), "글이 아님": (STAGE_BUILT, 5)}
        for label, (stage, branch) in bad.items():
            with self.subTest(label=label):
                raises(self, "CONTENT_INVALID", self.journal.write, PublishRecord("p1", ss.KO_PATH, COMMIT, "b" * 40, stage, branch))
                self.assertFalse((self.folder / "p1.json").exists(), "거절하면 파일을 만들지 않는다")

    def test_a_record_that_does_not_fit_is_not_read_and_the_file_is_left_alone(self):
        good = {"schema": 2, "project_id": "p1", "path": ss.KO_PATH, "commit": COMMIT, "base": "b" * 40, "stage": "built", "branch": BRANCH}
        cases = {"가지 칸 없음(판 2 인데 칸 여섯)": {key: value for key, value in good.items() if key != "branch"}, "판 1 인데 가지 칸이 있다": {**good, "schema": 1}, "모르는 칸": {**good, "extra": 1},
                 "판 3": {**good, "schema": 3}, "판이 참": {**good, "schema": True}, "가지 단계가 판 1": {"schema": 1, "project_id": "p1", "path": ss.KO_PATH, "commit": COMMIT, "base": "b" * 40, "stage": "built"},
                 "가지 모양 틀림": {**good, "branch": "desktop/post-x"}, "단계 틀림": {**good, "stage": "done"}, "옛 방식에 가지": {**good, "stage": "committed"}, "가지가 비었는데 가지 단계": {**good, "branch": ""},
                 "다른 글 번호": {**good, "project_id": "p2"}}
        for label, data in cases.items():
            (self.folder / "p1.json").write_text(json.dumps(data), encoding="utf-8")
            before = digest(self.folder / "p1.json")
            with self.subTest(label=label):
                raises(self, "SETTINGS_INVALID", self.journal.read, "p1")
                self.assertEqual(digest(self.folder / "p1.json"), before, "읽을 수 없는 기록은 건드리지 않는다")
        (self.folder / "p1.json").write_text(json.dumps(good), encoding="utf-8")
        self.assertEqual(self.journal.read("p1").branch, BRANCH)

    def test_the_old_reading_rule_would_refuse_a_version_two_record(self):
        """옛 프로그램의 읽기 규칙은 '칸 여섯 + 판 1' 뿐이었다 — 새 기록은 그 규칙에 맞지 않으므로(칸 일곱·판 2) 옛 프로그램은 SETTINGS_INVALID 로 거절하고 파일을 건드리지 않는다."""
        self.journal.write(PublishRecord("p1", ss.KO_PATH, COMMIT, "b" * 40, STAGE_BUILT, BRANCH))
        raw = self.raw()
        self.assertNotEqual(set(raw), journal_module._LEGACY_KEYS)
        self.assertNotEqual(raw["schema"], journal_module.LEGACY_SCHEMA)


class StoreVersionThreeTest(unittest.TestCase):
    """PT-29 — 보관함 판 2 → 3."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.path = self.dir / "chanceblog.db"

    def pragma(self, path, name):
        with closing(sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True)) as db:
            return db.execute(f"PRAGMA {name}").fetchone()[0]

    def rows(self, path):
        with closing(sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True)) as db:
            return {table: db.execute(f"SELECT * FROM {table} ORDER BY 1, 2").fetchall() for (table,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY 1").fetchall()}

    def make_v2(self, path=None):
        """판 2 파일 — 판 3 과 표 구조가 같아서, 새로 만든 파일의 판 번호만 2 로 되돌려 만든다(글 하나를 넣어 둔다)."""
        path = Path(path or self.path)
        with Store.open(path) as store:
            store.save(approved_project("pv2"))
        with closing(sqlite3.connect(str(path), isolation_level=None)) as db:
            db.execute("PRAGMA user_version = 2")
        self.assertEqual(self.pragma(path, "user_version"), 2)
        return path

    def test_the_version_is_three_and_the_migration_table_has_the_new_step(self):
        self.assertEqual(SCHEMA_VERSION, 3)
        self.assertEqual(set(store_module.MIGRATIONS), {1, 2})
        self.assertEqual(store_module.MIN_SCHEMA_VERSION, 1)
        self.assertEqual(store_module._SHAPES[3], store_module._SHAPES[2], "판 3 은 표 구조가 판 2 와 같다")
        with Store.open(self.path) as store:
            self.assertEqual((store.schema_version, store.needs_migration), (3, False))
        self.assertEqual((self.pragma(self.path, "user_version"), self.pragma(self.path, "application_id")), (3, APPLICATION_ID))

    def test_a_fresh_file_has_the_same_tables_as_a_version_two_file_upgraded(self):
        fresh = self.dir / "fresh.db"
        with Store.open(fresh):
            pass
        old = self.make_v2(self.dir / "old.db")
        with Store.open(old):
            pass
        with closing(sqlite3.connect(str(fresh))) as one, closing(sqlite3.connect(str(old))) as two:
            shape = lambda db: sorted(db.execute("SELECT type, name, tbl_name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'").fetchall())
            self.assertEqual(shape(one), shape(two), "새 파일 = 옛 파일을 올린 것")

    def test_a_version_two_file_is_upgraded_with_a_v2_copy_and_loses_nothing(self):
        path = self.make_v2()
        before_rows = self.rows(path)
        before = digest(path)
        with Store.open(path) as store:
            self.assertEqual(store.schema_version, 3)
            loaded = store.load("pv2")
            self.assertEqual(loaded.variant(PAGES).status, st.APPROVED)
        self.assertEqual(self.pragma(path, "user_version"), 3)
        copy = path.with_name(path.name + ".v2.bak")
        self.assertTrue(copy.is_file())
        self.assertEqual((self.pragma(copy, "user_version"), self.pragma(copy, "application_id")), (2, APPLICATION_ID))
        self.assertEqual(self.rows(copy), before_rows, "사본은 올리기 전 내용 그대로다")
        self.assertEqual(self.rows(path), before_rows, "표의 행이 하나도 달라지지 않았다")
        self.assertNotEqual(digest(path), before, "본 파일은 판 번호가 올라 바뀌었다(사본은 SQLite 가 다시 쓴 파일이라 바이트가 같다고 보지 않고 행 단위로 견주었다)")
        self.assertEqual(sorted(entry.name for entry in self.dir.iterdir()), [path.name, copy.name], "사본 하나 말고 다른 파일이 남지 않았다")

    def test_an_existing_copy_is_never_overwritten_by_a_second_upgrade(self):
        path = self.make_v2()
        with Store.open(path):
            pass
        copy = path.with_name(path.name + ".v2.bak")
        stamp = digest(copy)
        with closing(sqlite3.connect(str(path), isolation_level=None)) as db:
            db.execute("PRAGMA user_version = 2")
            db.execute("UPDATE projects SET title = '다른 제목' WHERE project_id = 'pv2'")
        with Store.open(path):
            pass
        self.assertEqual(digest(copy), stamp, "있던 사본은 그대로")
        self.assertTrue(path.with_name(path.name + ".v2.2.bak").is_file(), "내용이 다르면 다음 이름으로 새로 만든다")

    def test_a_version_one_file_goes_straight_to_three_with_only_the_v1_copy(self):
        project = approved_project("p1x")
        store_v1.make_v1_file(self.path, projects=[project])
        with Store.open(self.path) as store:
            self.assertEqual(store.schema_version, 3)
            self.assertEqual(store.load("p1x").variant(PAGES).status, st.APPROVED)
            self.assertEqual(store.list_candidates(), [])
        self.assertEqual(self.pragma(self.path, "user_version"), 3)
        names = sorted(entry.name for entry in self.dir.iterdir())
        self.assertEqual(names, ["chanceblog.db", "chanceblog.db.v1.bak"], "판 1 파일은 사본을 하나만 두고 한 번에 3 으로 오른다(.v2.bak 은 없다)")
        self.assertEqual(self.pragma(self.path.with_name("chanceblog.db.v1.bak"), "user_version"), 1)

    def test_an_older_program_refuses_a_version_three_file_and_does_not_touch_it(self):
        with Store.open(self.path) as store:
            store.save(approved_project("pv3"))
        before = digest(self.path)
        with mock.patch.object(store_module, "SCHEMA_VERSION", 2), mock.patch.object(store_module, "MIGRATIONS", {1: store_module._add_candidates}):
            exc = raises(self, "STORE_VERSION_UNSUPPORTED", Store.open, self.path)
            self.assertIn("3", exc.detail)
        self.assertEqual(digest(self.path), before, "옛 프로그램이 거절했을 뿐 파일은 한 바이트도 바뀌지 않았다")
        self.assertEqual(sorted(entry.name for entry in self.dir.iterdir()), [self.path.name], "사본도 만들지 않았다")

    def test_a_version_three_backup_is_not_restored_by_an_older_program_and_a_version_two_backup_is_restored_and_raised(self):
        with Store.open(self.path) as store:
            store.save(approved_project("pv3"))
            made = store.backup(self.dir / "backups")
        self.assertEqual(self.pragma(made, "user_version"), 3, "새 백업은 판 3 이다")
        other = self.dir / "other.db"
        with Store.open(other) as target:
            with mock.patch.object(store_module, "SCHEMA_VERSION", 2), mock.patch.object(store_module, "MIGRATIONS", {1: store_module._add_candidates}):
                raises(self, "STORE_VERSION_UNSUPPORTED", target.restore_from, made)
        old = self.make_v2(self.dir / "v2.db")
        with Store.open(other) as target:
            target.restore_from(old)
            self.assertEqual(target.schema_version, 3, "판 2 백업은 복원하면 3 으로 오른다")
            self.assertEqual(target.load("pv2").variant(PAGES).status, st.APPROVED)
        self.assertEqual(self.pragma(other, "user_version"), 3)

    def test_the_step_fails_and_rolls_back_when_the_version_two_tables_are_not_what_they_should_be(self):
        path = self.make_v2()
        with closing(sqlite3.connect(str(path), isolation_level=None)) as db:
            db.execute("DROP INDEX candidates_status")
        before = digest(path)
        raises(self, "MIGRATION_FAILED", Store.open, path)
        self.assertEqual(self.pragma(path, "user_version"), 2, "올리다 실패하면 판 번호도 그대로다")
        self.assertEqual(digest(path), before)


if __name__ == "__main__":
    unittest.main()
