"""서비스 층 — 글(프로젝트) 다루기 시험: 만들기·HTML 불러오기·목록·보기·고치기·지우기·백업·복구(네트워크·git 없음, 임시 폴더).

지키는 것:
  1) 글 번호는 전체 또는 앞 4자 이상이 겹치지 않는 앞부분으로 찾는다(없으면 CONTENT_NOT_FOUND, 여러 개와 맞으면 CONTENT_INVALID).
  2) 원고를 고치면 승인이 풀려 처음부터 다시 검토한다(모델의 규칙을 우회하지 않는다). 바뀐 것이 없으면 판 번호도 그대로다.
  3) 지우기는 확인(`confirmed is True`)이 있어야만 하고, 올리지 않은 글 기록(COMMITTED)이 있는 글은 지우지 않는다. 지우면 발행 기록 파일도 함께 지운다.
  4) 백업은 점검한 사본이고, 복구는 이 프로그램의 온전한 백업이 아니면 아무것도 바꾸지 않으며 바꾸기 직전 상태를 먼저 따로 백업한다.
"""
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import service_support as ss  # noqa: E402

from chanceblog_desktop.content import status as st  # noqa: E402
from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.service import projects  # noqa: E402
from chanceblog_desktop.service.journal import STAGE_COMMITTED, Journal, PublishRecord  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.ctx = ss.make_ctx(self.tmp)

    def new(self, title="첫 글", text="본문 첫 문단입니다.\n\n둘째 문단입니다.", **kwargs):
        return projects.new_project(self.ctx, title, text, **kwargs)


class CreateTest(Base):
    def test_a_markdown_post_is_created_and_saved_with_every_platform_not_started(self):
        view = self.new(references=["https://example.com/a"], assets=[projects.parse_asset("a.png|그림|1")])
        self.assertEqual((view.title, view.revision, view.created_at, view.updated_at), ("첫 글", 1, "2026-11-02T01:30:12Z", "2026-11-02T01:30:12Z"))
        self.assertEqual(view.references, ("https://example.com/a",))
        self.assertEqual([(asset.filename, asset.alt, asset.position) for asset in view.assets], [("a.png", "그림", 1)])
        self.assertEqual({item.platform: item.status for item in view.variants}, {name: st.NOT_STARTED for name in st.PLATFORMS})
        self.assertEqual([item.platform for item in view.variants], list(st.PLATFORMS), "화면에 보이는 순서는 Pages 가 먼저다")
        shown = projects.show_project(self.ctx, view.project_id)
        self.assertEqual((shown.title, shown.source_content), ("첫 글", "본문 첫 문단입니다.\n\n둘째 문단입니다."))

    def test_an_empty_title_or_body_or_a_bad_reference_is_refused_and_nothing_is_saved(self):
        for kwargs in ({"title": ""}, {"title": "x" * 201}, {"text": "   "}, {"references": ["javascript:alert(1)"]}, {"references": ["https://u:p@example.com/"]}):
            with self.subTest(kwargs=str(kwargs)[:40]):
                self.assertEqual(ss.code_of(self.new, **kwargs).code, "CONTENT_INVALID")
        self.assertEqual(projects.list_projects(self.ctx), [])

    def test_html_is_imported_as_markdown_without_scripts_or_attributes(self):
        html = '<h2>제목입니다</h2><p onclick="steal()">첫 <strong>문단</strong>입니다.</p><script>alert(1)</script><ul><li>하나</li><li>둘</li></ul>'
        view = projects.import_html(self.ctx, "불러온 글", html)
        text = projects.show_project(self.ctx, view.project_id).source_content
        self.assertIn("## 제목입니다", text)
        self.assertIn("**문단**", text)
        self.assertIn("- 하나", text)
        self.assertNotIn("alert", text)
        self.assertNotIn("onclick", text)

    def test_html_with_no_text_is_refused(self):
        for html in ("", "   ", "<script>alert(1)</script>", "<div></div>"):
            with self.subTest(html=html):
                error = ss.code_of(projects.import_html, self.ctx, "빈 글", html)
                self.assertEqual(error.code, "CONTENT_INVALID")
                self.assertIn("글자를 찾지 못했다", error.detail)

    def test_the_asset_text_is_parsed_strictly(self):
        self.assertEqual(projects.parse_asset("a.png"), projects.parse_asset("a.png||0"))
        asset = projects.parse_asset(" b.png | 설명 | 3 ")
        self.assertEqual((asset.filename, asset.alt, asset.position), ("b.png", "설명", 3))
        for bad in ("", "|설명", "a.png|x|y", "a.png|x|1|extra", "a/b.png|x|1"):
            with self.subTest(text=bad):
                self.assertEqual(ss.code_of(projects.parse_asset, bad).code, "CONTENT_INVALID")


class ResolveTest(Base):
    def test_the_full_number_and_a_unique_prefix_find_the_post(self):
        view = self.new()
        with self.ctx.store() as store:
            self.assertEqual(projects.resolve_id(store, view.project_id), view.project_id)
            self.assertEqual(projects.resolve_id(store, "  " + view.project_id[:6] + "  "), view.project_id)

    def test_too_short_unknown_or_ambiguous_numbers_are_refused_with_the_right_code(self):
        a = projects.new_project(self.ctx, "가", "본문 가", )
        with self.ctx.store() as store:
            for text, code in (("", "CONTENT_INVALID"), (None, "CONTENT_INVALID"), (a.project_id[:3], "CONTENT_NOT_FOUND"), ("zzzzzz", "CONTENT_NOT_FOUND")):
                with self.subTest(text=text):
                    self.assertEqual(ss.code_of(projects.resolve_id, store, text).code, code)
        # 같은 앞부분을 가진 번호 둘(앞 4자가 같다) — 번호를 직접 정해 만든다
        from chanceblog_desktop.content.model import ContentProject
        with self.ctx.store() as store:
            store.save(ContentProject.new("나", "본문 나", project_id="abcd1111", now="2026-11-02T00:00:00Z"))
            store.save(ContentProject.new("다", "본문 다", project_id="abcd2222", now="2026-11-02T00:00:00Z"))
            self.assertEqual(ss.code_of(projects.resolve_id, store, "abcd").code, "CONTENT_INVALID")
            self.assertEqual(projects.resolve_id(store, "abcd1"), "abcd1111")
            self.assertEqual(projects.resolve_id(store, "abcd2222"), "abcd2222", "전체 번호는 늘 맞는다")

    def test_an_id_that_looks_like_sql_is_just_not_found(self):
        self.new()
        with self.ctx.store() as store:
            self.assertEqual(ss.code_of(projects.resolve_id, store, "x' OR '1'='1").code, "CONTENT_NOT_FOUND")


class ListAndShowTest(Base):
    def test_an_empty_store_lists_nothing(self):
        self.assertEqual(projects.list_projects(self.ctx), [])

    def test_the_list_shows_every_posts_statuses_most_recently_changed_first(self):
        first = self.new("먼저")
        self.ctx.clock.advance(minutes=5)
        second = self.new("나중")
        rows = projects.list_projects(self.ctx)
        self.assertEqual([row.title for row in rows], ["나중", "먼저"])
        self.assertEqual(rows[0].statuses, {name: st.NOT_STARTED for name in st.PLATFORMS})
        self.assertEqual(rows[1].project_id, first.project_id)
        self.assertEqual(rows[0].to_dict()["error"], "")
        self.assertEqual(second.project_id, rows[0].project_id)

    def test_a_post_that_cannot_be_read_is_listed_with_its_error_code_not_hidden(self):
        view = self.new("멀쩡한 글")
        bad = self.new("깨진 글")
        with closing(sqlite3.connect(str(self.ctx.workspace.store_path))) as db:
            db.execute("UPDATE projects SET data = ? WHERE project_id = ?", ("{깨짐", bad.project_id))
            db.commit()
        rows = {row.project_id: row for row in projects.list_projects(self.ctx)}
        self.assertEqual(rows[bad.project_id].error, "STORE_CORRUPT")
        self.assertEqual(rows[bad.project_id].statuses, {})
        self.assertEqual(rows[view.project_id].error, "")

    def test_show_and_the_json_shape(self):
        view = self.new(text="본문 한 줄")
        shown = projects.show_project(self.ctx, view.project_id[:8])
        data = shown.to_dict()
        self.assertEqual((data["source_chars"], "source_content" in data), (len("본문 한 줄"), False))
        self.assertEqual(shown.to_dict(with_text=True)["source_content"], "본문 한 줄")
        self.assertEqual(ss.code_of(projects.show_project, self.ctx, "ffffffff").code, "CONTENT_NOT_FOUND")


class EditTest(Base):
    def test_editing_bumps_the_revision_and_saves(self):
        view = self.new()
        self.ctx.clock.advance(minutes=1)
        result = projects.edit_project(self.ctx, view.project_id, title="고친 제목", markdown="고친 본문")
        self.assertEqual((result.changed, result.project.revision, result.project.title), (True, 2, "고친 제목"))
        self.assertEqual(result.project.updated_at, "2026-11-02T01:31:12Z")
        self.assertEqual(projects.show_project(self.ctx, view.project_id).source_content, "고친 본문")

    def test_nothing_changed_means_nothing_saved_and_the_revision_stays(self):
        view = self.new()
        result = projects.edit_project(self.ctx, view.project_id, title="첫 글")
        self.assertEqual((result.changed, result.project.revision, result.reset_platforms), (False, 1, ()))
        self.assertEqual(projects.edit_project(self.ctx, view.project_id).changed, False)

    def test_editing_an_approved_post_revokes_the_approval_and_says_so(self):
        project_id = ss.make_approved(self.ctx)
        self.assertEqual(ss.status_of(self.ctx, project_id), st.APPROVED)
        result = projects.edit_project(self.ctx, project_id, markdown=ss.ko_text(1600))
        self.assertEqual(result.reset_platforms, ("github_pages",))
        self.assertEqual(ss.status_of(self.ctx, project_id), st.DRAFT_GENERATED, "승인이 풀리고 처음부터 다시 검토한다")

    def test_the_approval_can_never_survive_an_edit_even_after_review_only(self):
        view = self.new(text=ss.ko_text())
        from chanceblog_desktop.service import review
        review.request_review(self.ctx, view.project_id, "github_pages", pages=ss.KO_PARAMS)
        self.assertEqual(ss.status_of(self.ctx, view.project_id), st.REVIEW_REQUIRED)
        projects.edit_project(self.ctx, view.project_id, title="다른 제목")
        self.assertEqual(ss.status_of(self.ctx, view.project_id), st.DRAFT_GENERATED)

    def test_a_bad_edit_is_refused_and_leaves_the_post_as_it_was(self):
        view = self.new()
        for kwargs in ({"title": ""}, {"markdown": "  "}, {"references": ["ftp://x"]}):
            with self.subTest(kwargs=str(kwargs)):
                self.assertEqual(ss.code_of(projects.edit_project, self.ctx, view.project_id, **kwargs).code, "CONTENT_INVALID")
        shown = projects.show_project(self.ctx, view.project_id)
        self.assertEqual((shown.revision, shown.title), (1, "첫 글"))

    def test_references_and_images_can_be_replaced_and_cleared(self):
        view = self.new(references=["https://example.com/a"])
        projects.edit_project(self.ctx, view.project_id, references=("https://example.com/b", "https://example.com/c"), assets=(projects.parse_asset("x.png|설명|0"),))
        shown = projects.show_project(self.ctx, view.project_id)
        self.assertEqual((shown.references, len(shown.assets), shown.revision), (("https://example.com/b", "https://example.com/c"), 1, 2))
        projects.edit_project(self.ctx, view.project_id, references=(), assets=())
        shown = projects.show_project(self.ctx, view.project_id)
        self.assertEqual((shown.references, shown.assets, shown.revision), ((), (), 3))


class DeleteTest(Base):
    def test_without_the_confirmation_nothing_is_deleted(self):
        view = self.new()
        for confirmed in (False, None, 0, 1, "yes", "True", [True]):
            with self.subTest(confirmed=confirmed):
                self.assertEqual(ss.code_of(projects.delete_project, self.ctx, view.project_id, confirmed=confirmed).code, "CONFIRMATION_REQUIRED")
        self.assertEqual(len(projects.list_projects(self.ctx)), 1)

    def test_with_the_confirmation_the_post_and_its_publish_record_are_deleted(self):
        view = self.new()
        journal = Journal(self.ctx.workspace.journal_dir)
        journal.write(PublishRecord(view.project_id, ss.KO_PATH, "c" * 40, "b" * 40, STAGE_COMMITTED))
        deleted, note = projects.delete_project(self.ctx, view.project_id[:8], confirmed=True)
        self.assertEqual(deleted, view.project_id)
        self.assertIn("지우기 직전 상태를 백업해 두었습니다", note)
        self.assertEqual(projects.list_projects(self.ctx), [])
        self.assertIsNone(journal.read(view.project_id))
        saved = sorted((self.ctx.workspace.backups_dir / "before-delete").iterdir())
        self.assertEqual(len(saved), 1, "지우기 직전의 백업이 있다")
        self.assertIn(str(saved[0]), note)
        projects.restore_store(self.ctx, saved[0], confirmed=True)                                  # 잘못 지웠으면 그 백업으로 되살릴 수 있다
        self.assertEqual([row.project_id for row in projects.list_projects(self.ctx)], [view.project_id])

    def test_two_deletes_in_the_same_second_keep_both_pre_delete_backups(self):
        first, second = self.new(), projects.new_project(self.ctx, "둘째 글", ss.ko_text(1200))
        projects.delete_project(self.ctx, first.project_id, confirmed=True)
        projects.delete_project(self.ctx, second.project_id, confirmed=True)
        self.assertEqual(len(list((self.ctx.workspace.backups_dir / "before-delete").iterdir())), 2, "같은 초에 지워도 앞의 백업을 덮어쓰지 않는다")

    def test_a_post_with_a_commit_that_was_never_pushed_is_not_deleted(self):
        project_id = ss.make_approved(self.ctx)
        self.ctx.backend.push_errors = [AppError("GIT_PUSH_NETWORK")]
        from chanceblog_desktop.service import pages_flow
        with self.assertRaises(AppError):
            pages_flow.run_pages_publish(self.ctx, project_id, confirmed=True)
        self.assertEqual(ss.status_of(self.ctx, project_id), st.COMMITTED)
        error = ss.code_of(projects.delete_project, self.ctx, project_id, confirmed=True)
        self.assertEqual((error.code, error.slots["현재 상태"]), ("STATUS_TRANSITION_INVALID", st.COMMITTED))
        self.assertEqual(len(projects.list_projects(self.ctx)), 1, "올리지 않은 글 기록이 주인 없이 남지 않게 지우지 않는다")

    def test_a_post_that_is_already_published_can_be_deleted_from_the_app(self):
        project_id = ss.make_approved(self.ctx)
        from chanceblog_desktop.service import pages_flow
        pages_flow.run_pages_publish(self.ctx, project_id, confirmed=True)
        self.assertEqual(projects.delete_project(self.ctx, project_id, confirmed=True)[0], project_id)

    def test_an_unreadable_post_can_still_be_deleted(self):
        view = self.new()
        with closing(sqlite3.connect(str(self.ctx.workspace.store_path))) as db:
            db.execute("UPDATE projects SET data = ? WHERE project_id = ?", ("{깨짐", view.project_id))
            db.commit()
        self.assertEqual(projects.delete_project(self.ctx, view.project_id, confirmed=True)[0], view.project_id)

    def test_an_unknown_post_is_not_found(self):
        self.assertEqual(ss.code_of(projects.delete_project, self.ctx, "ffffffff", confirmed=True).code, "CONTENT_NOT_FOUND")

    def test_a_read_problem_other_than_a_damaged_post_stops_the_deletion(self):
        from unittest import mock
        from chanceblog_desktop.content.store import Store
        view = self.new()
        with mock.patch.object(Store, "load", side_effect=AppError("STORE_LOCKED")):
            self.assertEqual(ss.code_of(projects.delete_project, self.ctx, view.project_id, confirmed=True).code, "STORE_LOCKED")
        self.assertEqual(len(projects.list_projects(self.ctx)), 1)


class BackupTest(Base):
    def test_a_backup_is_a_checked_copy_in_the_backup_folder(self):
        self.new()
        path = projects.backup_store(self.ctx)
        self.assertEqual(path.parent, self.ctx.workspace.backups_dir)
        self.assertEqual(path.name, "chanceblog-20261102-013012.db")
        with closing(sqlite3.connect(str(path))) as db:
            self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(db.execute("SELECT COUNT(*) FROM projects").fetchone()[0], 1)
        self.assertEqual(projects.list_backups(self.ctx), [path])

    def test_restoring_brings_deleted_posts_back_and_backs_up_the_state_it_replaced(self):
        view = self.new("지켜야 할 글")
        backup = projects.backup_store(self.ctx)
        projects.delete_project(self.ctx, view.project_id, confirmed=True)
        self.new("그 뒤에 만든 글")
        source, safety = projects.restore_store(self.ctx, backup, confirmed=True)
        self.assertEqual((source, safety), (backup, self.ctx.workspace.backups_dir / "before-restore"))
        self.assertEqual([row.title for row in projects.list_projects(self.ctx)], ["지켜야 할 글"])
        saved = list(safety.glob("chanceblog-*.db"))
        self.assertEqual(len(saved), 1, "바꾸기 직전 상태를 먼저 백업했다")
        with closing(sqlite3.connect(str(saved[0]))) as db:
            self.assertEqual([row[0] for row in db.execute("SELECT title FROM projects")], ["그 뒤에 만든 글"])

    def test_latest_picks_the_newest_backup_and_none_is_refused(self):
        self.new("하나")
        self.assertEqual(ss.code_of(projects.restore_store, self.ctx, None, latest=True, confirmed=True).code, "CONTENT_NOT_FOUND")
        old = projects.backup_store(self.ctx)
        self.ctx.clock.advance(minutes=10)
        self.new("둘")
        newest = projects.backup_store(self.ctx)
        self.assertEqual(projects.list_backups(self.ctx), [newest, old])
        source, _ = projects.restore_store(self.ctx, None, latest=True, confirmed=True)
        self.assertEqual(source, newest)
        self.assertEqual(len(projects.list_projects(self.ctx)), 2)

    def test_a_file_that_is_not_a_backup_of_this_program_changes_nothing(self):
        self.new("그대로")
        stranger = self.tmp / "other.db"
        with closing(sqlite3.connect(str(stranger))) as db:
            db.execute("CREATE TABLE x (a)")
            db.commit()
        junk = self.tmp / "junk.db"
        junk.write_bytes(b"not a database at all" * 50)
        before = self.ctx.workspace.store_path.read_bytes()
        for path in (stranger, junk, self.tmp / "missing.db"):
            with self.subTest(file=path.name):
                self.assertIn(ss.code_of(projects.restore_store, self.ctx, path, confirmed=True).code, ("STORE_CORRUPT", "FILE_WRITE_FAILED"))
        self.assertEqual([row.title for row in projects.list_projects(self.ctx)], ["그대로"])
        self.assertEqual(self.ctx.workspace.store_path.read_bytes(), before)

    def test_without_a_file_or_latest_it_asks_for_one(self):
        self.assertEqual(ss.code_of(projects.restore_store, self.ctx, None, confirmed=True).code, "CONTENT_INVALID")


if __name__ == "__main__":
    unittest.main()
