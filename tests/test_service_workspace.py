"""서비스 층 — 작업 공간·설정·Context 시험(네트워크·진짜 git 없음, 임시 폴더).

지키는 것:
  1) 사용자 데이터 폴더는 Windows 의 `%LOCALAPPDATA%/ChanceblogDesktop` 이 기본이고 `--data-dir`·환경 변수로 바꿀 수 있지만, **저장소(git) 안이나 프로그램 폴더 안은 거절**한다(DATA_DIR_UNSAFE).
  2) 설정 파일은 연결한 chanceblog 폴더와 네이버 프로필만 담고(키·토큰 없음), 임시 파일에 쓴 뒤 바꿔 넣으며, 깨졌거나 모양이 틀리면 건드리지 않고 SETTINGS_INVALID.
  3) 연결한 저장소 폴더는 `--repo` > 저장해 둔 설정 > 환경 변수 순이고, 아무것도 없으면 PAGES_LOCAL_REPO_INVALID. 시계는 시간대가 있어야 한다.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import service_support as ss  # noqa: E402

from chanceblog_desktop.content.profiles import NaverProfile  # noqa: E402
from chanceblog_desktop.service import context  # noqa: E402
from chanceblog_desktop.service.context import Settings, Workspace  # noqa: E402

ROOT = ss.ROOT


def profile(key="naver_a", name="블로그 에이", url="https://blog.naver.com/exampleaaa", **kwargs):
    return NaverProfile(key, name, url, **kwargs)


class DataFolderTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)

    def test_on_windows_the_default_is_the_local_app_data_folder(self):
        found = context.default_data_dir({"LOCALAPPDATA": str(self.tmp / "Local")}, windows=True)
        self.assertEqual(found, self.tmp / "Local" / "ChanceblogDesktop")

    def test_on_windows_without_the_variable_it_falls_back_to_the_user_profile(self):
        found = context.default_data_dir({}, windows=True, home=self.tmp)
        self.assertEqual(found, self.tmp / "AppData" / "Local" / "ChanceblogDesktop")

    def test_elsewhere_the_default_is_the_xdg_data_folder(self):
        self.assertEqual(context.default_data_dir({"XDG_DATA_HOME": str(self.tmp / "x")}, windows=False), self.tmp / "x" / "ChanceblogDesktop")
        self.assertEqual(context.default_data_dir({}, windows=False, home=self.tmp), self.tmp / ".local" / "share" / "ChanceblogDesktop")

    def test_the_flag_beats_the_environment_variable_beats_the_default(self):
        env = {"CHANCEBLOG_DESKTOP_DATA": str(self.tmp / "from_env"), "LOCALAPPDATA": str(self.tmp / "Local")}
        self.assertEqual(Workspace.resolve(str(self.tmp / "from_flag"), env=env).root, self.tmp / "from_flag")
        self.assertEqual(Workspace.resolve(None, env=env).root, self.tmp / "from_env")
        self.assertEqual(Workspace.resolve(None, env={"LOCALAPPDATA": str(self.tmp / "Local"), "XDG_DATA_HOME": str(self.tmp / "Local")}).root.name, "ChanceblogDesktop")

    def make_link(self, link, target):
        """폴더 링크(Windows 는 권한 없이 되는 정션)를 만든다 — 못 만들면 False."""
        try:
            os.symlink(target, link, target_is_directory=True)
            return True
        except (OSError, NotImplementedError):
            if os.name != "nt":
                return False
        done = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True)
        return done.returncode == 0

    def test_a_link_that_points_inside_a_git_repository_or_the_program_folder_is_refused_by_where_it_really_goes(self):
        repo = self.tmp / "somerepo"
        (repo / ".git").mkdir(parents=True)
        (repo / "data").mkdir()
        link = self.tmp / "innocent-looking"
        if not self.make_link(link, repo / "data"):
            self.skipTest("이 PC 에서는 폴더 링크를 만들 수 없다")
        error = ss.code_of(Workspace.resolve, str(link), env={})
        self.assertEqual(error.code, "DATA_DIR_UNSAFE")
        self.assertIn("git 저장소 안이다", error.detail)
        program = self.tmp / "program-link"
        self.assertTrue(self.make_link(program, ROOT / "src"))
        self.assertIn("프로그램 폴더 안이다", ss.code_of(Workspace.resolve, str(program), env={}).detail)

    def test_resolving_does_not_create_anything_but_ensure_does(self):
        workspace = Workspace.resolve(str(self.tmp / "new" / "data"), env={})
        self.assertFalse((self.tmp / "new").exists())
        workspace.ensure()
        self.assertTrue((self.tmp / "new" / "data").is_dir())

    def test_the_files_live_under_the_data_folder_with_fixed_names(self):
        workspace = Workspace(self.tmp / "d")
        self.assertEqual((workspace.store_path.name, workspace.settings_path.name, workspace.backups_dir.name, workspace.journal_dir.name), ("chanceblog.db", "settings.json", "backups", "publish"))
        for path in (workspace.store_path, workspace.settings_path, workspace.backups_dir, workspace.journal_dir):
            self.assertEqual(path.parent, self.tmp / "d")

    def test_a_folder_inside_a_git_repository_is_refused_and_nothing_is_created(self):
        (self.tmp / "repo" / ".git").mkdir(parents=True)
        for inside in (self.tmp / "repo", self.tmp / "repo" / "data", self.tmp / "repo" / "a" / "b"):
            with self.subTest(folder=str(inside.relative_to(self.tmp))):
                error = ss.code_of(Workspace.resolve, str(inside), env={})
                self.assertEqual(error.code, "DATA_DIR_UNSAFE")
        self.assertFalse((self.tmp / "repo" / "data").exists())

    def test_the_same_applies_to_the_environment_variable(self):
        (self.tmp / "repo" / ".git").mkdir(parents=True)
        error = ss.code_of(Workspace.resolve, None, env={"CHANCEBLOG_DESKTOP_DATA": str(self.tmp / "repo" / "data")})
        self.assertEqual(error.code, "DATA_DIR_UNSAFE")

    def test_the_programs_own_folder_is_refused(self):
        for inside in (ROOT / "userdata_for_test", ROOT / "src", ROOT):
            with self.subTest(folder=inside.name):
                self.assertEqual(ss.code_of(Workspace.resolve, str(inside), env={}).code, "DATA_DIR_UNSAFE")

    def test_a_git_file_instead_of_a_folder_also_marks_a_work_tree(self):
        """git 은 하위 모듈·작업 트리에서 `.git` 을 파일로 둔다."""
        (self.tmp / "wt").mkdir()
        (self.tmp / "wt" / ".git").write_text("gitdir: ../elsewhere\n", encoding="utf-8")
        self.assertEqual(ss.code_of(Workspace.resolve, str(self.tmp / "wt" / "data"), env={}).code, "DATA_DIR_UNSAFE")

    def test_a_folder_outside_any_repository_is_fine_and_the_refusal_names_the_path_but_no_secret(self):
        self.assertEqual(Workspace.resolve(str(self.tmp / "ok"), env={}).root, self.tmp / "ok")
        (self.tmp / "r" / ".git").mkdir(parents=True)
        error = ss.code_of(Workspace.resolve, str(self.tmp / "r"), env={})
        self.assertIn("git 저장소", error.detail)
        self.assertEqual(error.slots["경로"], str(self.tmp / "r"))

    def test_the_default_folder_is_never_inside_the_program_folder(self):
        self.assertEqual(context.unsafe_reason(context.default_data_dir({}, windows=True, home=self.tmp)), "")

    def test_an_unwritable_place_is_a_file_error_not_a_crash(self):
        blocker = self.tmp / "blocker"
        blocker.write_text("파일", encoding="utf-8")
        error = ss.code_of(Workspace(blocker / "sub").ensure)
        self.assertEqual(error.code, "FILE_WRITE_FAILED")


class SettingsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.path = self.tmp / "data" / "settings.json"
        self.settings = Settings(self.path)

    def test_reading_without_a_file_gives_defaults_and_creates_nothing(self):
        self.assertEqual(self.settings.repo_path(), "")
        self.assertEqual(self.settings.naver_profile_dicts(), {})
        self.assertFalse(self.path.parent.exists())

    def test_the_saved_file_has_exactly_the_known_keys_and_no_secret_slot(self):
        self.settings.save_repo_path(self.tmp / "chanceblog")
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(sorted(data), ["naver_profiles", "repo_path", "schema"])
        self.assertEqual(data["repo_path"], str(self.tmp / "chanceblog"))
        self.assertEqual(Settings(self.path).repo_path(), str(self.tmp / "chanceblog"))

    def test_saving_leaves_no_temporary_file_behind(self):
        self.settings.save_repo_path("x")
        self.settings.save_naver_profile(profile())
        self.assertEqual(sorted(entry.name for entry in self.path.parent.iterdir()), ["settings.json"])

    def test_a_failed_replace_keeps_the_old_file_and_cleans_up(self):
        self.settings.save_repo_path("처음")
        before = self.path.read_bytes()
        with mock.patch.object(context.os, "replace", side_effect=OSError("denied")):
            error = ss.code_of(self.settings.save_repo_path, "새것")
        self.assertEqual(error.code, "FILE_WRITE_FAILED")
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(sorted(entry.name for entry in self.path.parent.iterdir()), ["settings.json"])

    def test_a_temporary_file_that_cannot_be_removed_is_named_in_the_detail_not_hidden(self):
        with mock.patch.object(context.os, "replace", side_effect=OSError("denied")), mock.patch.object(Path, "unlink", side_effect=PermissionError("잠김")):
            error = ss.code_of(self.settings.save_repo_path, "x")
        self.assertEqual(error.code, "FILE_WRITE_FAILED")
        self.assertIn("임시 파일도 지우지 못했다(PermissionError)", error.detail)

    def test_a_full_disk_is_reported_as_such(self):
        import errno
        with mock.patch.object(context.os, "replace", side_effect=OSError(errno.ENOSPC, "no space")):
            self.assertEqual(ss.code_of(self.settings.save_repo_path, "x").code, "DISK_FULL")

    def test_a_damaged_or_odd_file_is_refused_and_left_untouched(self):
        cases = {
            "깨진 JSON": "{not json", "빈 파일": "", "목록": "[]", "칸이 모자람": '{"schema": 1}', "모르는 칸": '{"schema": 1, "repo_path": "", "naver_profiles": {}, "extra": 1}',
            "다른 판": '{"schema": 2, "repo_path": "", "naver_profiles": {}}', "경로가 글이 아님": '{"schema": 1, "repo_path": 5, "naver_profiles": {}}',
            "프로필이 목록": '{"schema": 1, "repo_path": "", "naver_profiles": []}', "모르는 블로그": '{"schema": 1, "repo_path": "", "naver_profiles": {"naver_c": {}}}',
            "프로필 값이 글": '{"schema": 1, "repo_path": "", "naver_profiles": {"naver_a": "x"}}',
        }
        for name, text in cases.items():
            with self.subTest(case=name):
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self.path.write_text(text, encoding="utf-8")
                before = self.path.read_bytes()
                for call in (self.settings.repo_path, self.settings.naver_profile_dicts, lambda: self.settings.save_repo_path("x")):
                    error = ss.code_of(call)
                    self.assertEqual((error.code, error.slots["파일"]), ("SETTINGS_INVALID", "settings.json"))
                self.assertEqual(self.path.read_bytes(), before, "읽을 수 없는 파일을 덮어쓰지 않는다")

    def test_a_non_utf8_file_is_refused(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_bytes(b"\xff\xfe\x00bad")
        self.assertEqual(ss.code_of(self.settings.repo_path).code, "SETTINGS_INVALID")

    def test_a_folder_in_place_of_the_file_is_refused(self):
        self.path.mkdir(parents=True)
        self.assertEqual(ss.code_of(self.settings.repo_path).code, "SETTINGS_INVALID")

    def test_a_naver_profile_round_trips_and_a_missing_one_has_its_own_code(self):
        saved = profile(topic="경제", default_tags=("경제", "생활"), categories={"경제": "경제 이야기"})
        self.settings.save_naver_profile(saved)
        self.assertEqual(self.settings.naver_profile("naver_a"), saved)
        error = ss.code_of(self.settings.naver_profile, "naver_b")
        self.assertEqual((error.code, error.slots["블로그"]), ("NAVER_PROFILE_MISSING", "naver_b"))
        self.assertEqual(sorted(self.settings.naver_profile_dicts()), ["naver_a"])

    def test_saving_a_profile_keeps_the_connected_folder_and_the_other_profile(self):
        self.settings.save_repo_path("폴더")
        self.settings.save_naver_profile(profile("naver_a"))
        self.settings.save_naver_profile(profile("naver_b", "블로그 비", "https://blog.naver.com/examplebbb"))
        self.assertEqual(self.settings.repo_path(), "폴더")
        self.assertEqual(sorted(self.settings.naver_profile_dicts()), ["naver_a", "naver_b"])

    def test_a_stored_profile_that_no_longer_validates_is_a_settings_error(self):
        self.path.parent.mkdir(parents=True)
        bad = {"schema": 1, "repo_path": "", "naver_profiles": {"naver_a": {"key": "naver_a", "display_name": "x", "blog_url": "http://not-naver.example/x"}}}
        self.path.write_text(json.dumps(bad), encoding="utf-8")
        self.assertEqual(ss.code_of(self.settings.naver_profile, "naver_a").code, "SETTINGS_INVALID")

    def test_a_profile_stored_under_the_other_blogs_key_is_refused(self):
        self.path.parent.mkdir(parents=True)
        mixed = {"schema": 1, "repo_path": "", "naver_profiles": {"naver_b": profile("naver_a").to_dict()}}
        self.path.write_text(json.dumps(mixed), encoding="utf-8")
        self.assertEqual(ss.code_of(self.settings.naver_profile, "naver_b").code, "SETTINGS_INVALID")

    def test_only_a_naver_profile_object_can_be_saved(self):
        self.assertEqual(ss.code_of(self.settings.save_naver_profile, {"key": "naver_a"}).code, "CONTENT_INVALID")


class ContextTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)

    def test_the_clock_must_carry_a_time_zone_and_comes_back_as_utc(self):
        ctx = ss.make_ctx(self.tmp, clock=lambda: datetime(2026, 11, 2, 10, 30, 12))
        self.assertEqual(ss.code_of(ctx.now).code, "CONTENT_INVALID")
        ctx = ss.make_ctx(self.tmp / "b", clock=lambda: "지금")
        self.assertEqual(ss.code_of(ctx.now).code, "CONTENT_INVALID")
        from datetime import timedelta
        ctx = ss.make_ctx(self.tmp / "c", clock=lambda: datetime(2026, 11, 2, 10, 30, 12, tzinfo=timezone(timedelta(hours=9))))
        self.assertEqual(ctx.now(), datetime(2026, 11, 2, 1, 30, 12, tzinfo=timezone.utc))
        self.assertEqual(ctx.stamp(), "2026-11-02T01:30:12Z")

    def test_the_connected_folder_comes_from_the_flag_then_the_saved_setting_then_the_environment(self):
        ctx = ss.make_ctx(self.tmp, repo=None)
        self.assertEqual(ss.code_of(ctx.repo_path).code, "PAGES_LOCAL_REPO_INVALID")
        self.assertIsNone(ctx.repo_path_or_none())
        ctx.env = {"CHANCEBLOG_LOCAL_REPO": str(self.tmp / "from_env")}
        self.assertEqual(ctx.repo_path(), self.tmp / "from_env")
        ctx.settings.save_repo_path(str(self.tmp / "saved"))
        self.assertEqual(ctx.repo_path(), self.tmp / "saved", "저장해 둔 연결이 환경 변수보다 앞선다")
        ctx.repo_override = str(self.tmp / "flag")
        self.assertEqual(ctx.repo_path(), self.tmp / "flag")

    def test_a_damaged_settings_file_is_never_taken_for_no_connection(self):
        ctx = ss.make_ctx(self.tmp, repo=None)
        ctx.settings.path.parent.mkdir(parents=True, exist_ok=True)
        ctx.settings.path.write_text("{깨짐", encoding="utf-8")
        for call in (ctx.repo_path, ctx.repo_path_or_none, ctx.local_paths):
            self.assertEqual(ss.code_of(call).code, "SETTINGS_INVALID")

    def test_a_blank_setting_counts_as_not_connected(self):
        ctx = ss.make_ctx(self.tmp, repo=None)
        ctx.settings.save_repo_path("   ")
        self.assertEqual(ss.code_of(ctx.repo_path).code, "PAGES_LOCAL_REPO_INVALID")

    def test_local_paths_lists_the_data_folder_and_the_connected_folder(self):
        ctx = ss.make_ctx(self.tmp)
        self.assertEqual(ctx.local_paths(), (str(ctx.workspace.root), str(self.tmp / "chanceblog")))
        self.assertEqual(ss.make_ctx(self.tmp / "x", repo=None).local_paths(), (str(self.tmp / "x" / "data"),))

    def test_the_store_opens_in_the_data_folder_and_creates_it(self):
        ctx = ss.make_ctx(self.tmp, repo=None)
        self.assertFalse(ctx.workspace.root.exists())
        with ctx.store() as store:
            self.assertEqual(store.path, ctx.workspace.store_path)
            self.assertEqual(store.list(), [])
        self.assertTrue(ctx.workspace.store_path.is_file())

    def test_make_context_builds_the_real_parts_with_the_guarded_data_folder(self):
        ctx = context.make_context(data_dir=str(self.tmp / "d"), repo=str(self.tmp / "r"), env={})
        self.assertEqual((ctx.workspace.root, ctx.repo_override), (self.tmp / "d", str(self.tmp / "r")))
        self.assertEqual(type(ctx.backend).__name__, "LocalOnlyBackend")          # 의도적 갱신(PCSEC1 H3): 꽂힌 외부 어댑터가 없으면(이 빌드는 늘 없다) 파일만 읽는 backend 가 기본이다(예전: GitPagesBackend)
        self.assertEqual(ctx.git.__name__, "refusing_git")                        # 기본 git 실행기는 어떤 호출도 거절한다
        (self.tmp / "g" / ".git").mkdir(parents=True)
        self.assertEqual(ss.code_of(context.make_context, data_dir=str(self.tmp / "g" / "d"), env={}).code, "DATA_DIR_UNSAFE")


if __name__ == "__main__":
    unittest.main()
