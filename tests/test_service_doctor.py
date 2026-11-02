"""서비스 층 — doctor(점검) 시험. 읽기만 하는 점검이 항목마다 한 줄 결과(쉬운 한국어)와 오류 코드를 낸다.

지키는 것:
  1) **아무것도 쓰지 않는다**: 없는 데이터 폴더·글 저장소·설정 파일을 새로 만들지 않고, 있는 파일은 한 바이트도 바꾸지 않는다. 네트워크는 `--online` 일 때 올리기 권한 점검 하나뿐이다.
  2) 항목: 프로그램 버전·Python·git·데이터 폴더·설정 파일·글 저장소(깨짐 포함)·백업·가져온 핵심 코드(vendor/ 해시)·연결한 저장소(올리지 않은 글 기록 포함)·올리기 권한·네이버 프로필·이어서 처리할 글.
  3) 점검 하나가 막혀도(AppError) 나머지는 계속하고, 문제(주의·실패)에는 오류 코드와 하실 일을 붙인다. 고쳐야 할 것(fail)이 있을 때만 정상이 아니다.
"""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import service_support as ss  # noqa: E402

from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.publish.gitrepo import GitResult  # noqa: E402
from chanceblog_desktop.service import doctor, pages_flow, projects  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.backend = ss.FakeBackend()
        self.ctx = ss.make_ctx(self.tmp, backend=self.backend)

    def run_doctor(self, **kwargs):
        return {item.name + ("" if not isinstance(item, list) else ""): item for item in doctor.run_doctor(self.ctx, **kwargs)}

    def results(self, **kwargs):
        return doctor.run_doctor(self.ctx, **kwargs)

    def find(self, name, **kwargs):
        return next(item for item in self.results(**kwargs) if item.name == name)


class OverallTest(Base):
    def test_a_healthy_setup_has_nothing_to_fix(self):
        projects.new_project(self.ctx, "글", ss.ko_text())
        projects.backup_store(self.ctx)
        results = self.results()
        self.assertTrue(doctor.doctor_ok(results))
        self.assertEqual([item.status for item in results if item.status == "fail"], [])
        names = [item.name for item in results]
        for expected in ("프로그램 버전", "Python", "git", "데이터 폴더", "설정 파일", "글 저장소", "백업", "핵심 코드(vendor/)", "연결한 chanceblog 저장소", "올리기 권한", "네이버 A 프로필", "네이버 B 프로필"):
            self.assertIn(expected, names)

    def test_every_result_is_one_line_with_a_known_status_and_a_code_only_for_problems(self):
        projects.new_project(self.ctx, "글", ss.ko_text())
        for item in self.results():
            self.assertIn(item.status, ("ok", "warn", "fail", "skip"))
            self.assertNotIn("\n", item.message)
            if item.status == "ok":
                self.assertEqual((item.code, item.action), ("", ""))
            self.assertEqual(sorted(item.to_dict()), ["action", "code", "message", "name", "status"])

    def test_the_program_version_and_python_are_reported(self):
        self.assertEqual(self.find("프로그램 버전").message, "버전 " + (ss.ROOT / "VERSION").read_text(encoding="utf-8").strip())
        self.assertEqual(doctor.app_version(), (ss.ROOT / "VERSION").read_text(encoding="utf-8").strip())
        self.assertIn(".".join(str(part) for part in sys.version_info[:3]), self.find("Python").message)

    def test_a_python_that_is_too_old_is_a_failure(self):
        with mock.patch.object(doctor.sys, "version_info", (3, 9, 1, "final", 0)):
            item = self.find("Python")
        self.assertEqual((item.status, item.code), ("fail", "UNEXPECTED_ERROR"))

    def test_one_failing_check_does_not_stop_the_others(self):
        self.ctx.settings.path.parent.mkdir(parents=True, exist_ok=True)
        self.ctx.settings.path.write_text("{깨짐", encoding="utf-8")
        results = self.results()
        self.assertEqual(self.find("설정 파일").code, "SETTINGS_INVALID")
        repo = self.find("연결한 chanceblog 저장소")
        self.assertEqual((repo.status, repo.code), ("fail", "SETTINGS_INVALID"), "깨진 설정을 '연결 안 함' 으로 숨기지 않는다")
        self.assertGreater(len(results), 8)
        self.assertFalse(doctor.doctor_ok(results))


class ReadOnlyTest(Base):
    def test_a_fresh_machine_gets_a_check_without_creating_anything(self):
        ctx = ss.make_ctx(self.tmp / "fresh", backend=self.backend, repo=None)
        results = doctor.run_doctor(ctx)
        self.assertFalse((self.tmp / "fresh").exists(), "데이터 폴더도 글 저장소도 설정 파일도 만들지 않는다")
        by_name = {item.name: item for item in results}
        for name in ("데이터 폴더", "설정 파일", "글 저장소"):
            self.assertEqual(by_name[name].status, "ok")
            self.assertIn("아직 없습니다", by_name[name].message)

    def test_an_empty_data_file_is_not_filled_in_by_the_check(self):
        self.ctx.workspace.ensure()
        self.ctx.workspace.store_path.write_bytes(b"")
        item = self.find("글 저장소")
        self.assertEqual((item.status, item.code), ("ok", ""))
        self.assertEqual(self.ctx.workspace.store_path.read_bytes(), b"", "점검이 빈 파일에 구조를 만들어 넣지 않는다")

    def test_existing_files_are_not_changed_by_even_one_byte(self):
        projects.new_project(self.ctx, "글", ss.ko_text())
        projects.backup_store(self.ctx)
        self.ctx.settings.save_repo_path(str(self.tmp / "chanceblog"))
        before = ss.tree_snapshot(self.tmp)
        self.results(online=True)
        self.assertEqual(ss.tree_snapshot(self.tmp), before)

    def test_the_network_check_is_only_done_when_asked_for(self):
        offline = self.find("올리기 권한")
        self.assertEqual((offline.status, self.backend.count("check_push_access")), ("skip", 0))
        online = self.find("올리기 권한", online=True)
        self.assertEqual((online.status, self.backend.count("check_push_access")), ("ok", 1))
        self.assertIn("실제로는 올리지 않았습니다", online.message)

    def test_a_push_access_problem_is_a_failure_with_its_code_and_what_to_do(self):
        self.backend.inspect_error = AppError("GIT_PUSH_AUTH")
        item = self.find("올리기 권한", online=True)
        self.assertEqual((item.status, item.code), ("fail", "GIT_PUSH_AUTH"))
        self.assertIn("git push", item.action)

    def test_without_a_connected_folder_the_push_check_is_skipped(self):
        ctx = ss.make_ctx(self.tmp / "x", backend=self.backend, repo=None)
        item = next(item for item in doctor.run_doctor(ctx, online=True) if item.name == "올리기 권한")
        self.assertEqual(item.status, "skip")
        self.assertEqual(self.backend.count("check_push_access"), 0)


class StoreTest(Base):
    def test_the_post_count_is_reported(self):
        projects.new_project(self.ctx, "하나", ss.ko_text())
        projects.new_project(self.ctx, "둘", ss.ko_text())
        self.assertIn("글 2개", self.find("글 저장소").message)

    def test_a_file_that_is_not_this_programs_data_is_a_failure_and_stays_untouched(self):
        self.ctx.workspace.ensure()
        self.ctx.workspace.store_path.write_bytes(b"not a database" * 100)
        before = self.ctx.workspace.store_path.read_bytes()
        item = self.find("글 저장소")
        self.assertEqual((item.status, item.code), ("fail", "STORE_CORRUPT"))
        self.assertEqual(self.ctx.workspace.store_path.read_bytes(), before)

    def test_a_row_that_cannot_be_read_is_found_by_the_stores_own_check(self):
        import sqlite3
        from contextlib import closing
        view = projects.new_project(self.ctx, "깨질 글", ss.ko_text())
        with closing(sqlite3.connect(str(self.ctx.workspace.store_path))) as db:
            db.execute("UPDATE projects SET data = ? WHERE project_id = ?", ("{깨짐", view.project_id))
            db.commit()
        item = self.find("글 저장소")
        self.assertEqual((item.status, item.code), ("fail", "STORE_CORRUPT"))
        self.assertIn("문제 1개", item.message)
        self.assertIn(view.project_id, item.message)

    def test_a_newer_programs_file_is_refused_not_opened(self):
        import sqlite3
        from contextlib import closing
        projects.new_project(self.ctx, "글", ss.ko_text())
        with closing(sqlite3.connect(str(self.ctx.workspace.store_path))) as db:
            db.execute("PRAGMA user_version = 99")
            db.commit()
        self.assertEqual(self.find("글 저장소").code, "STORE_VERSION_UNSUPPORTED")

    def test_backups_are_counted_and_none_is_only_a_warning(self):
        warning = self.find("백업")
        self.assertEqual((warning.status, warning.code), ("warn", ""))
        projects.new_project(self.ctx, "글", ss.ko_text())
        path = projects.backup_store(self.ctx)
        ok = self.find("백업")
        self.assertEqual(ok.status, "ok")
        self.assertIn(path.name, ok.message)

    def test_a_data_folder_that_cannot_be_written_is_a_failure(self):
        projects.new_project(self.ctx, "글", ss.ko_text())
        with mock.patch.object(doctor.os, "access", return_value=False):
            item = self.find("데이터 폴더")
        self.assertEqual((item.status, item.code), ("fail", "FILE_WRITE_FAILED"))


class CoreCodeTest(Base):
    def test_the_real_vendored_core_matches_its_record(self):
        item = self.find("핵심 코드(vendor/)")
        self.assertEqual((item.status, item.code), ("ok", ""))
        manifest = (ss.ROOT / "vendor" / "VENDOR.json").read_text(encoding="utf-8")
        import json
        self.assertIn(json.loads(manifest)["ref"][:12], item.message)

    def test_a_mismatch_found_by_the_import_scripts_own_check_is_a_failure_naming_the_first_problem(self):
        class Fake:
            @staticmethod
            def check():
                return ["pipeline/gates.py: 내용이 VENDOR.json 의 해시와 다르다", "다른 문제"]

        with mock.patch.object(doctor, "_load_sync_core", return_value=Fake):
            item = self.find("핵심 코드(vendor/)")
        self.assertEqual((item.status, item.code), ("fail", "CORE_CODE_MISMATCH"))
        self.assertIn("2곳", item.message)
        self.assertIn("pipeline/gates.py", item.message)
        self.assertIn("프로그램 파일이 바뀌었습니다", item.action)
        self.assertIn("다시 내려받거나", item.action)
        for developer_word in ("sync_core.py", "git restore", "vendor"):
            self.assertNotIn(developer_word, item.action, "일반 사용자에게 개발 명령을 시키지 않는다")

    def test_when_the_check_tool_is_not_there_it_says_it_was_skipped(self):
        with mock.patch.object(doctor, "_load_sync_core", return_value=None):
            item = self.find("핵심 코드(vendor/)")
        self.assertEqual((item.status, item.code), ("skip", ""))

    def test_the_check_tool_is_the_repositorys_own_function_loaded_by_path(self):
        module = doctor._load_sync_core()
        self.assertIs(module, doctor._load_sync_core(), "한 번만 읽는다")
        self.assertEqual(module.check(), [])
        self.assertEqual(Path(module.__file__).resolve(), (ss.ROOT / "scripts" / "sync_core.py").resolve())


class InstalledCopyTest(Base):
    """VERSION·scripts/·VENDOR.json 이 없는 설치본 같은 곳에서도 점검이 멈추지 않는다."""

    def fake_root(self, name="fake_root"):
        root = self.tmp / name
        root.mkdir()
        return root

    def test_without_a_version_file_the_version_is_unknown_not_an_error(self):
        with mock.patch.object(doctor, "REPO_ROOT", self.fake_root()):
            self.assertEqual(doctor.app_version(), "알 수 없음")
            self.assertEqual(self.find("프로그램 버전").status, "ok")
        empty = self.fake_root("empty_version")
        (empty / "VERSION").write_text("  \n", encoding="utf-8")
        with mock.patch.object(doctor, "REPO_ROOT", empty):
            self.assertEqual(doctor.app_version(), "알 수 없음")

    def test_without_the_scripts_folder_the_core_check_is_skipped(self):
        with mock.patch.object(doctor, "REPO_ROOT", self.fake_root()):
            self.assertIsNone(doctor._load_sync_core())
            self.assertEqual(self.find("핵심 코드(vendor/)").status, "skip")

    def test_a_check_script_that_cannot_be_loaded_is_an_error_and_leaves_no_half_loaded_module(self):
        root = self.fake_root()
        (root / "scripts").mkdir()
        (root / "scripts" / "sync_core.py").write_text("raise RuntimeError('깨진 스크립트')\n", encoding="utf-8")
        with mock.patch.object(doctor, "REPO_ROOT", root), mock.patch.dict(sys.modules):
            sys.modules.pop("chanceblog_desktop_sync_core", None)
            with self.assertRaises(RuntimeError):
                doctor._load_sync_core()
            self.assertNotIn("chanceblog_desktop_sync_core", sys.modules)

    def test_an_unreadable_vendor_record_just_leaves_the_commit_out_of_the_message(self):
        root = self.fake_root()
        (root / "vendor").mkdir()
        for text in ("{깨짐", "[]", '{"ref": 5}'):
            with self.subTest(text=text):
                (root / "vendor" / "VENDOR.json").write_text(text, encoding="utf-8")
                with mock.patch.object(doctor, "REPO_ROOT", root):
                    self.assertEqual(doctor._vendor_ref(), "")
        with mock.patch.object(doctor, "REPO_ROOT", self.tmp / "nothing"):
            self.assertEqual(doctor._vendor_ref(), "")


class RepoTest(Base):
    def test_the_check_only_reads_the_connected_repository_and_never_rewrites_the_settings(self):
        self.ctx.settings.save_repo_path(str(self.tmp / "chanceblog"))
        before = self.ctx.settings.path.read_bytes()
        self.find("연결한 chanceblog 저장소")
        self.assertEqual(self.ctx.settings.path.read_bytes(), before)
        self.assertEqual(self.backend.names(), ["inspect", "unpushed_count"])

    def test_a_connected_clean_repository_is_fine(self):
        item = self.find("연결한 chanceblog 저장소")
        self.assertEqual((item.status, item.code), ("ok", ""))
        self.assertIn("main", item.message)

    def test_no_connected_folder_is_a_warning_with_the_invalid_repo_code(self):
        ctx = ss.make_ctx(self.tmp / "x", backend=self.backend, repo=None)
        item = next(item for item in doctor.run_doctor(ctx) if item.name == "연결한 chanceblog 저장소")
        self.assertEqual((item.status, item.code), ("warn", "PAGES_LOCAL_REPO_INVALID"))
        self.assertIn("connect", item.message)

    def test_a_repository_that_is_not_in_order_is_a_failure_with_its_own_code_and_guidance(self):
        for code in ("PAGES_LOCAL_REPO_DIRTY", "PAGES_LOCAL_REPO_NOT_MAIN", "PAGES_LOCAL_REPO_INVALID"):
            with self.subTest(code=code):
                self.backend.inspect_error = AppError(code, {"브랜치": "dev"})
                item = self.find("연결한 chanceblog 저장소")
                self.assertEqual((item.status, item.code), ("fail", code))
                self.assertTrue(item.action)

    def test_commits_that_were_never_pushed_are_a_warning_with_the_next_step(self):
        self.backend.unpushed = 2
        item = self.find("연결한 chanceblog 저장소")
        self.assertEqual((item.status, item.code), ("warn", "PAGES_LOCAL_REPO_DIVERGED"))
        self.assertIn("2개", item.message)
        self.assertIn("git log origin/main..HEAD", item.action, "앱이 만든 글 기록이 아닌 commit — 사람이 확인하라는 한 가지 안내")
        self.assertNotIn("이어받아", item.action)

    def test_git_that_cannot_run_is_a_failure(self):
        self.ctx.git = mock.Mock(side_effect=AppError("GIT_NOT_INSTALLED"))
        item = self.find("git")
        self.assertEqual((item.status, item.code), ("fail", "GIT_NOT_INSTALLED"))
        self.ctx.git = lambda cwd, args, timeout=0, input_bytes=None: GitResult(1, "", "boom")
        self.assertEqual(self.find("git").code, "GIT_NOT_INSTALLED")


class PendingAndProfilesTest(Base):
    def test_posts_waiting_to_be_pushed_or_verified_are_named_with_their_commands(self):
        stuck = ss.make_approved(self.ctx, title="올리다 멈춘 글")
        self.backend.push_errors = [AppError("GIT_PUSH_NETWORK")]
        with self.assertRaises(AppError):
            pages_flow.run_pages_publish(self.ctx, stuck, confirmed=True)
        self.ctx.clock.advance(seconds=5)
        waiting = ss.make_approved(self.ctx, title="공개 확인이 남은 글")
        pages_flow.run_pages_publish(self.ctx, waiting, confirmed=True, wait=False)
        items = [item for item in self.results() if item.name == "이어서 처리할 글"]
        self.assertEqual(sorted(item.status for item in items), ["warn", "warn"])
        text = " ".join(item.message for item in items)
        self.assertIn(f"publish-pages {stuck[:8]} --yes", text)
        self.assertIn(f"check-deploy {waiting[:8]}", text)
        self.assertEqual({item.code for item in items}, {"PAGES_LOCAL_REPO_DIVERGED", "PAGES_DEPLOY_NOT_VISIBLE"})

    def test_an_approved_post_whose_commit_was_left_without_a_record_is_named_with_both_ways_out(self):
        """commit 직후에 멈춘 흔적 — 승인됨 + 기록 없는 commit. doctor 가 이어받기와 되돌리기 두 길을 실제 명령으로 알려 준다."""
        from chanceblog_desktop.publish.pages import CommitInfo
        project_id = ss.make_approved(self.ctx, title="기록 직후 멈춘 글")
        self.assertEqual([item for item in self.results() if item.name == "이어서 처리할 글"], [], "그런 commit 이 없으면 아무 말도 하지 않는다")
        self.backend.orphan = CommitInfo(ss.KO_PATH, "c" * 40, "b" * 40)
        self.backend.unpushed = 1                                          # 기록 없는 commit 이 하나 있다(진짜 저장소에서는 orphan 이 있으면 늘 1)
        items = [item for item in self.results() if item.name == "이어서 처리할 글"]
        self.assertEqual(len(items), 1)
        self.assertEqual((items[0].status, items[0].code), ("warn", "PAGES_LOCAL_REPO_DIVERGED"))
        self.assertIn("기록(commit) 직후에 멈춘 흔적", items[0].message)
        self.assertIn(f"publish-pages {project_id[:8]} --yes", items[0].message)
        self.assertIn(f"publish-pages {project_id[:8]} --cancel --yes", items[0].message)
        self.assertIn("이어받아", items[0].message)

    def test_an_unreadable_post_is_a_failure_that_names_it(self):
        import sqlite3
        from contextlib import closing
        view = projects.new_project(self.ctx, "읽을 수 없는 글", ss.ko_text())
        with closing(sqlite3.connect(str(self.ctx.workspace.store_path))) as db:
            db.execute("UPDATE projects SET data = ? WHERE project_id = ?", ("{깨짐", view.project_id))
            db.commit()
        item = self.find("글 읽기")
        self.assertEqual((item.status, item.code), ("fail", "STORE_CORRUPT"))
        self.assertIn(view.project_id[:8], item.message)

    def test_naver_profiles_are_shown_when_set_and_skipped_when_not(self):
        self.assertEqual([item.status for item in self.results() if item.name.startswith("네이버")], ["skip", "skip"])
        ss.naver_profiles(self.ctx, both=False)
        items = {item.name: item for item in self.results()}
        self.assertEqual((items["네이버 A 프로필"].status, items["네이버 B 프로필"].status), ("ok", "skip"))
        self.assertIn("블로그 에이", items["네이버 A 프로필"].message)

    def test_nothing_pending_means_no_pending_lines(self):
        projects.new_project(self.ctx, "그냥 글", ss.ko_text())
        self.assertEqual([item for item in self.results() if item.name == "이어서 처리할 글"], [])


if __name__ == "__main__":
    unittest.main()
