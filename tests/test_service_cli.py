"""서비스 층 — 명령줄(`python -m chanceblog_desktop`) 시험. 같은 프로세스에서 `main(argv)` 를 불러 종료 코드·표준 출력·표준 오류를 확인하고, 몇 개는 실제로 프로세스를 띄워 본다.

지키는 것:
  1) 종료 코드: 0 정상 · 1 처리된 오류 · 2 사용법 오류. 예상한 오류(AppError)에 스택 추적을 보이지 않고 코드·원인·하실 일(·다시 시도·세부)을 쉬운 한국어로 보인다(오류는 표준 오류로).
  2) **확인 없이는 올리지 않는다**: `publish-pages` 는 기본이 미리 보기(아무것도 안 함)이고 `--yes` 가 있어야 commit·push 한다. 올리기 취소·글 지우기도 `--yes` 가 있어야 한다.
  3) 화면에 나가는 모든 글(일반·오류·JSON)은 비밀 모양을 가린다 — 원고·제목·오류 세부에 키 모양 문자열이 있어도 출력에는 없다. 키·토큰은 읽지 않는다.
  4) `--json` 은 `{"ok", "command", "data"}`(오류면 `error`)이고, 전역 옵션은 명령 앞뒤 어디에 써도 된다. 예상하지 못한 오류는 UNEXPECTED_ERROR 로 안내하고 `--debug` 에서만 그대로 낸다.
"""
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import service_support as ss  # noqa: E402

from chanceblog_desktop.content import status as st  # noqa: E402
from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.service import cli, projects  # noqa: E402

PAGES = ["--category", "경제·일", "--lang", "ko", "--image-url", "https://images.example.invalid/a.jpg", "--tags", "에너지,생활"]


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.backend = ss.FakeBackend()
        self.ctx = ss.make_ctx(self.tmp, backend=self.backend)

    def cli(self, *argv, **kwargs):
        return ss.run_cli(self.ctx, *argv, **kwargs)

    def ok(self, *argv):
        code, out, err = self.cli(*argv)
        self.assertEqual((code, err), (0, ""), f"{argv}: {err}")
        return out

    def data(self, *argv):
        out = self.ok("--json", *argv)
        payload = json.loads(out)
        self.assertEqual((payload["ok"], payload["command"]), (True, argv[0]))
        return payload["data"]

    def new_post(self, title="에너지 절약 습관", text=None):
        return self.data("new", "--title", title, "--text", text or ss.ko_text())["project"]["project_id"]

    def approved(self):
        project_id = self.new_post()
        self.ok("review", project_id, "--platform", "pages", *PAGES)
        self.ok("approve", project_id, "--platform", "pages")
        self.backend.calls.clear()
        return project_id

    def status(self, project_id, platform="github_pages"):
        return ss.status_of(self.ctx, project_id, platform)

    def fails(self, *argv, code=1):
        got, out, err = self.cli(*argv)
        self.assertEqual(got, code, f"{argv}: {out} {err}")
        self.assertNotIn("Traceback", out + err)
        return out, err


class UsageTest(Base):
    def test_no_command_is_a_usage_error_in_korean_with_a_hint(self):
        out, err = self.fails(code=2)
        self.assertEqual(out, "")
        self.assertIn("사용법 오류: 빠진 항목이 있습니다", err)
        self.assertIn("--help", err)

    def test_an_unknown_command_or_choice_is_a_usage_error_naming_the_allowed_values(self):
        _out, err = self.fails("frobnicate", code=2)
        self.assertIn("쓸 수 없는 값", err)
        self.assertIn("doctor", err)
        _out, err = self.fails("review", "abcd1234", "--platform", "fax", code=2)
        self.assertIn("--platform", err)
        self.assertIn("naver_a", err)

    def test_missing_values_numbers_and_unknown_options_are_usage_errors(self):
        _out, err = self.fails("new", code=2)
        self.assertIn("--title", err)
        _out, err = self.fails("new", "--title", code=2)
        self.assertIn("값이 필요합니다", err)
        _out, err = self.fails("check-deploy", "abcd1234", "--wait", "abc", code=2)
        self.assertIn("숫자", err)
        _out, err = self.fails("list", "--bogus", code=2)
        self.assertIn("알 수 없는 항목", err)

    def test_the_manuscript_must_come_from_exactly_one_place(self):
        _out, err = self.fails("new", "--title", "제목", code=2)
        self.assertIn("--file", err)
        self.assertIn("--text", err)
        file = self.tmp / "a.md"
        file.write_text("본문", encoding="utf-8")
        self.fails("new", "--title", "제목", "--file", str(file), "--text", "본문", code=2)
        self.assertEqual(projects.list_projects(self.ctx), [])

    def test_the_github_pages_settings_are_required_for_review_and_preview(self):
        project_id = self.new_post()
        for command in ("review", "preview"):
            with self.subTest(command=command):
                _out, err = self.fails(command, project_id, "--platform", "pages", code=2)
                self.assertIn("--category", err)
        _out, err = self.fails("review", project_id, "--platform", "pages", *PAGES, "--source-name", "출처만", code=2)
        self.assertIn("--source-url", err)
        self.assertEqual(self.status(project_id), st.NOT_STARTED)

    def test_help_exits_zero_and_prints_to_standard_output_in_korean(self):
        code, out, err = self.cli("--help")
        self.assertEqual((code, err), (0, ""))
        for needle in ("publish-pages", "doctor", "--yes", "미리 보기"):
            self.assertIn(needle, out)
        code, out, err = self.cli("publish-pages", "--help")
        self.assertEqual((code, err), (0, ""))
        for needle in ("--yes", "--no-wait", "--cancel", "기본은 미리 보기"):
            self.assertIn(needle, out)
        self.assertEqual(self.backend.calls, [])

    def test_global_options_work_before_and_after_the_command(self):
        self.new_post()
        for argv in (("--json", "list"), ("list", "--json")):
            with self.subTest(argv=argv):
                self.assertEqual(len(json.loads(self.ok(*argv))["data"]["projects"]), 1)


class MaskingLayersTest(unittest.TestCase):
    """출력의 가리기는 여러 층이다(오류 문구를 만드는 곳·화면에 쓰는 곳·JSON 으로 바꾸는 곳). 어느 한 층이 빠져도 다른 층이 가려 주지만, 층마다 따로 확인해 둔다."""

    def test_the_error_lines_hide_a_key_in_the_detail_and_in_the_listed_items(self):
        from chanceblog_desktop.service import format as fmt
        for error in (AppError("GIT_PUSH_AUTH", detail=f"remote: token {ss.KEY} failed"), AppError("CHECK_FAILED", {"걸린 항목 목록": "LEN_SHORT"}, detail=f"[LEN_SHORT] {ss.KEY}; [LANG] 또 하나"),
                      AppError("NAVER_SIMILARITY_HIGH", detail=f"본문 유사도 90% {ss.KEY}")):
            with self.subTest(code=error.code):
                text = "\n".join(fmt.error_lines(error, verbose=True))
                self.assertNotIn(ss.KEY, text)
                self.assertIn("[가림:", text)

    def test_the_text_printer_hides_a_key_even_if_a_line_arrived_unmasked(self):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(cli.fmt, "error_lines", return_value=[f"오류 {ss.KEY}"]):
            cli._report_error(out, err, "list", AppError("UNEXPECTED_ERROR"), False, False)
        self.assertNotIn(ss.KEY, err.getvalue())
        self.assertIn("[가림:", err.getvalue())
        self.assertEqual(out.getvalue(), "")

    def test_the_json_error_hides_a_key_in_every_field_even_without_the_other_layers(self):
        out, err = io.StringIO(), io.StringIO()
        error = AppError("GIT_PUSH_AUTH", detail=f"remote: https://u:{ss.KEY}@github.com/x failed")
        cli._report_error(out, err, "publish-pages", error, True, False)
        self.assertNotIn(ss.KEY, out.getvalue())
        self.assertEqual(json.loads(out.getvalue())["error"]["code"], "GIT_PUSH_AUTH")
        self.assertEqual(err.getvalue(), "")

    def test_the_json_error_detail_is_one_short_line(self):
        payload = cli._error_payload(AppError("GIT_PUSH_NETWORK", detail="줄 하나\n줄 둘   " + "길게 " * 1000))
        self.assertNotIn("\n", payload["detail"])
        self.assertNotIn("  ", payload["detail"])
        self.assertEqual(len(payload["detail"]), 700)

    def test_an_unexpected_exception_becomes_the_catch_all_error_with_the_secret_already_hidden(self):
        error = cli.unexpected_error(RuntimeError(f"boom {ss.KEY} " + "x" * 500))
        self.assertEqual(error.code, "UNEXPECTED_ERROR")
        self.assertNotIn(ss.KEY, error.detail)
        self.assertTrue(error.detail.startswith("RuntimeError: boom [가림:"))
        self.assertLessEqual(len(error.detail), 230)
        self.assertNotIn(ss.KEY, error.log_line())


class StreamTest(unittest.TestCase):
    def test_a_stream_that_can_be_reconfigured_is_told_to_replace_characters_it_cannot_show(self):
        class Stream(io.StringIO):
            def __init__(self):
                super().__init__()
                self.reconfigured = []

            def reconfigure(self, **kwargs):
                self.reconfigured.append(kwargs)

        out, err = Stream(), Stream()
        self.assertEqual(cli.main(["--help"], out=out, err=err), 0)
        self.assertEqual((out.reconfigured, err.reconfigured), ([{"errors": "replace"}], [{"errors": "replace"}]))

    def test_a_stream_that_refuses_the_change_does_not_stop_the_command(self):
        class Stubborn(io.StringIO):
            def reconfigure(self, **kwargs):
                raise ValueError("이미 쓰기 시작했다")

        out, err = Stubborn(), Stubborn()
        self.assertEqual(cli.main(["--help"], out=out, err=err), 0)
        self.assertIn("publish-pages", out.getvalue())


class HandledErrorTest(Base):
    def test_a_handled_error_shows_code_cause_and_what_to_do_on_standard_error_without_a_traceback(self):
        out, err = self.fails("show", "ffffffff")
        self.assertEqual(out, "")
        for needle in ("오류: 글을 찾을 수 없습니다", "코드: CONTENT_NOT_FOUND", "하실 일:", "다시 시도: 아니오"):
            self.assertIn(needle, err)

    def test_details_are_shown_for_guidance_and_the_verbose_line_only_when_asked(self):
        self.ctx.settings.path.parent.mkdir(parents=True, exist_ok=True)
        self.ctx.settings.path.write_text("{깨짐", encoding="utf-8")
        _out, err = self.fails("connect", str(self.tmp))
        self.assertIn("코드: SETTINGS_INVALID", err)
        self.assertIn("세부:", err)
        self.assertNotIn("기록용 한 줄", err)
        _out, err = self.fails("--verbose", "connect", str(self.tmp))
        self.assertIn("기록용 한 줄: SETTINGS_INVALID", err)

    def test_a_check_that_failed_lists_every_item_it_found(self):
        project_id = self.new_post(text="짧은 글입니다. " * 10)
        self.ok("review", project_id, "--platform", "pages", *PAGES)
        _out, err = self.fails("approve", project_id, "--platform", "pages")
        self.assertIn("코드: CHECK_FAILED", err)
        self.assertIn("걸린 항목:", err)
        self.assertIn("[LEN_SHORT]", err)

    def test_the_error_is_a_json_object_on_standard_output_in_json_mode(self):
        code, out, err = self.cli("--json", "show", "ffffffff")
        self.assertEqual((code, err), (1, ""))
        payload = json.loads(out)
        self.assertEqual((payload["ok"], payload["command"], payload["error"]["code"]), (False, "show", "CONTENT_NOT_FOUND"))
        self.assertEqual(sorted(payload["error"]), ["action", "code", "detail", "message", "retry"])

    def test_an_unexpected_error_is_announced_by_its_catch_all_code_with_secrets_hidden(self):
        with mock.patch.object(cli, "cmd_list", side_effect=RuntimeError(f"boom {ss.KEY}")):
            code, out, err = self.cli("list")
        self.assertEqual((code, out), (1, ""))
        self.assertIn("코드: UNEXPECTED_ERROR", err)
        self.assertIn("RuntimeError", err)
        self.assertNotIn(ss.KEY, err)
        self.assertNotIn("Traceback", err)

    def test_debug_lets_an_unexpected_error_through_for_developers(self):
        with mock.patch.object(cli, "cmd_list", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                self.cli("--debug", "list")

    def test_an_interruption_ends_with_exit_one_and_says_the_next_run_continues(self):
        with mock.patch.object(cli, "cmd_list", side_effect=KeyboardInterrupt):
            code, out, err = self.cli("list")
        self.assertEqual((code, out), (1, ""))
        self.assertIn("중단했습니다", err)
        self.assertIn("이어서", err)

    def test_the_data_folder_inside_a_repository_is_refused_before_anything_is_created(self):
        (self.tmp / "repo" / ".git").mkdir(parents=True)
        out, err, code = io.StringIO(), io.StringIO(), None
        code = cli.main(["--data-dir", str(self.tmp / "repo" / "data"), "list"], out=out, err=err, env={})
        self.assertEqual(code, 1)
        self.assertIn("코드: DATA_DIR_UNSAFE", err.getvalue())
        self.assertFalse((self.tmp / "repo" / "data").exists())


class ProjectCommandsTest(Base):
    def test_new_list_show_edit_and_delete_through_the_command_line(self):
        out = self.ok("new", "--title", "첫 글", "--text", "첫 문단입니다.\n\n둘째 문단입니다.", "--ref", "https://example.com/a", "--image", "a.png|그림|1")
        self.assertIn("글을 만들었습니다", out)
        self.assertIn(f"본문: {len('첫 문단입니다.' + chr(10) * 2 + '둘째 문단입니다.')}자   출처 주소: 1개   이미지: 1개", out)
        project_id = self.data("list")["projects"][0]["project_id"]
        self.assertIn(f"[{project_id[:8]}] 첫 글", self.ok("list"))
        shown = self.ok("show", project_id[:8], "--full")
        for needle in ("글: 첫 글", f"번호: {project_id}", "GitHub Pages: 시작 전 (NOT_STARTED)", "[본문]", "둘째 문단입니다."):
            self.assertIn(needle, shown)
        self.assertNotIn("Blogger", shown, "쓰지 않은 Blogger 칸은 보이지 않는다")
        self.assertNotIn("둘째 문단", self.ok("show", project_id), "본문은 --full 일 때만")
        self.assertIn("고쳤습니다(판 2)", self.ok("edit", project_id, "--title", "고친 제목"))
        self.assertIn("바뀐 것이 없습니다", self.ok("edit", project_id, "--title", "고친 제목"))
        self.assertIn("글을 지웠습니다", self.ok("delete", project_id, "--yes"))
        self.assertIn("글이 아직 없습니다", self.ok("list"))

    def test_a_post_that_cannot_be_read_is_still_listed_with_its_error_code(self):
        import sqlite3
        from contextlib import closing
        project_id = self.new_post("깨질 글")
        with closing(sqlite3.connect(str(self.ctx.workspace.store_path))) as db:
            db.execute("UPDATE projects SET data = ? WHERE project_id = ?", ("{깨짐", project_id))
            db.commit()
        self.assertIn("깨질 글 — 읽을 수 없습니다(오류 코드 STORE_CORRUPT)", self.ok("list"))

    def test_an_empty_list_points_to_how_to_start(self):
        self.assertIn("`new`", self.ok("list"))

    def test_editing_an_approved_post_says_the_approval_was_withdrawn(self):
        project_id = self.approved()
        out = self.ok("edit", project_id, "--text", ss.ko_text(1700))
        self.assertIn("검토·승인이 풀렸습니다", out)
        self.assertIn("GitHub Pages", out)
        self.assertEqual(self.status(project_id), st.DRAFT_GENERATED)

    def test_the_references_and_images_can_be_replaced_or_cleared(self):
        project_id = self.new_post()
        self.ok("edit", project_id, "--ref", "https://example.com/a", "--ref", "https://example.com/b", "--image", "x.png")
        shown = self.data("show", project_id)["project"]
        self.assertEqual((len(shown["references"]), len(shown["assets"])), (2, 1))
        self.ok("edit", project_id, "--clear-refs", "--clear-images")
        shown = self.data("show", project_id)["project"]
        self.assertEqual((shown["references"], shown["assets"]), ([], []))

    def test_importing_an_html_post(self):
        out = self.ok("import-html", "--title", "불러온 글", "--text", "<h2>소제목</h2><p>본문 <strong>글</strong></p><script>alert(1)</script>")
        self.assertIn("Markdown 으로 바꿔 불러왔습니다", out)
        project_id = self.data("list")["projects"][0]["project_id"]
        text = self.data("show", project_id, "--full")["project"]["source_content"]
        self.assertIn("## 소제목", text)
        self.assertNotIn("alert", text)
        self.fails("import-html", "--title", "빈 글", "--text", "<script>x</script>")

    def test_delete_without_the_confirmation_deletes_nothing(self):
        project_id = self.new_post()
        out, err = self.fails("delete", project_id)
        self.assertIn("CONFIRMATION_REQUIRED", err)
        self.assertIn("--yes", err)
        self.assertEqual(len(projects.list_projects(self.ctx)), 1)

    def test_files_are_read_as_utf8_with_or_without_a_bom_and_as_cp949(self):
        for name, data in (("utf8.md", "한글 원고 본문입니다".encode("utf-8")), ("bom.md", "﻿한글 원고 본문입니다".encode("utf-8")), ("cp949.md", "한글 원고 본문입니다".encode("cp949"))):
            with self.subTest(file=name):
                path = self.tmp / name
                path.write_bytes(data)
                project_id = self.data("new", "--title", name, "--file", str(path))["project"]["project_id"]
                self.assertEqual(self.data("show", project_id, "--full")["project"]["source_content"], "한글 원고 본문입니다")

    def test_a_missing_or_unreadable_file_is_a_content_error_not_a_crash(self):
        _out, err = self.fails("new", "--title", "제목", "--file", str(self.tmp / "없는 파일.md"))
        self.assertIn("CONTENT_INVALID", err)
        bad = self.tmp / "bad.md"
        bad.write_bytes(b"\xff\xfe\xfa\xfb\x80\x81")
        _out, err = self.fails("new", "--title", "제목", "--file", str(bad))
        self.assertIn("글자 모양", err)
        self.assertEqual(projects.list_projects(self.ctx), [])


class PagesCommandsTest(Base):
    def test_review_preview_approve_and_revoke_move_the_post_one_explicit_step_at_a_time(self):
        project_id = self.new_post()
        preview = self.ok("preview", project_id, "--platform", "pages", *PAGES)
        for needle in ("아무 파일도 쓰지 않았습니다", ss.KO_PATH, "공개 주소(예상)", "검사: 통과", "layout: post", "전체는 --full"):
            self.assertIn(needle, preview)
        self.assertEqual(self.status(project_id), st.NOT_STARTED)
        self.assertIn("검토 중으로 보냈습니다", self.ok("review", project_id, "--platform", "pages", *PAGES))
        self.assertEqual(self.status(project_id), st.REVIEW_REQUIRED)
        approved = self.ok("approve", project_id, "--platform", "pages")
        self.assertIn("승인했습니다", approved)
        self.assertIn("publish-pages", approved)
        self.assertEqual(self.status(project_id), st.APPROVED)
        self.assertIn("승인을 거뒀습니다", self.ok("revoke", project_id, "--platform", "pages"))
        self.assertEqual(self.status(project_id), st.REVIEW_REQUIRED)

    def test_the_platform_name_can_be_written_both_ways(self):
        project_id = self.new_post()
        self.ok("review", project_id, "--platform", "github_pages", *PAGES)
        self.assertEqual(self.status(project_id), st.REVIEW_REQUIRED)

    def test_the_source_options_reach_the_post(self):
        project_id = self.new_post()
        out = self.ok("preview", project_id, "--platform", "pages", *PAGES, "--source-name", "한국은행", "--source-url", "https://www.bok.or.kr/x", "--source-title", "보도자료", "--description", "직접 쓴 설명", "--full")
        for needle in ('source_name: "한국은행"', "[한국은행: 보도자료](https://www.bok.or.kr/x)", 'description: "직접 쓴 설명"'):
            self.assertIn(needle, out)

    def test_preview_full_shows_the_whole_text(self):
        project_id = self.new_post()
        short = self.ok("preview", project_id, "--platform", "pages", *PAGES)
        full = self.ok("preview", project_id, "--platform", "pages", *PAGES, "--full")
        self.assertGreater(len(full), len(short))
        self.assertNotIn("전체는 --full", full)

    def test_publish_pages_without_yes_is_a_preview_that_does_nothing(self):
        project_id = self.approved()
        out = self.ok("publish-pages", project_id)
        for needle in ("미리 보기 — 아직 아무것도 하지 않았습니다", ss.KO_PATH, "--yes", "할 일:"):
            self.assertIn(needle, out)
        self.assertEqual(self.backend.count("commit") + self.backend.count("push") + self.backend.count("discard") + self.backend.count("check_deployed"), 0)
        self.assertEqual(self.status(project_id), st.APPROVED)
        self.assertEqual(self.data("publish-pages", project_id)["dry_run"], True)

    def test_publish_pages_with_yes_commits_pushes_and_checks_the_address(self):
        project_id = self.approved()
        out = self.ok("publish-pages", project_id, "--yes")
        for needle in ("한 일:", "기록(commit)", "main 에 올렸습니다", "공개 주소가 열리는 것을 확인했습니다", "공개됨 (PUBLISHED)"):
            self.assertIn(needle, out)
        self.assertEqual([name for name in self.backend.names() if name in ("commit", "push", "check_deployed")], ["commit", "push", "check_deployed"])
        self.assertEqual(self.status(project_id), st.PUBLISHED)
        self.assertEqual(self.data("show", project_id)["project"]["variants"][0]["published_url"], ss.KO_URL)

    def test_no_wait_and_the_wait_time_reach_the_flow(self):
        project_id = self.approved()
        out = self.ok("publish-pages", project_id, "--yes", "--no-wait")
        self.assertIn("공개 확인은 하지 않았습니다", out)
        self.assertIn(f"check-deploy {project_id}", out)
        self.assertEqual(self.backend.count("check_deployed"), 0)
        self.ok("check-deploy", project_id, "--wait", "90")
        self.assertIn(("check_deployed", ss.KO_PATH, 90, 10), self.backend.calls)
        self.assertEqual(self.status(project_id), st.PUBLISHED)

    def test_the_wait_time_of_a_real_publish_reaches_the_deploy_check(self):
        project_id = self.approved()
        self.ok("publish-pages", project_id, "--yes", "--wait", "45")
        self.assertIn(("check_deployed", ss.KO_PATH, 45, 10), self.backend.calls)

    def test_an_unapproved_post_cannot_be_published_even_with_yes(self):
        project_id = self.new_post()
        _out, err = self.fails("publish-pages", project_id, "--yes")
        self.assertIn("STATUS_TRANSITION_INVALID", err)
        self.assertEqual(self.backend.calls, [])

    def test_a_deploy_that_is_not_open_yet_is_reported_as_pushed_with_exit_zero_and_the_retry_command(self):
        project_id = self.approved()
        self.backend.deploy_errors = [AppError("PAGES_DEPLOY_NOT_VISIBLE")]
        code, out, err = self.cli("publish-pages", project_id, "--yes")
        self.assertEqual((code, err), (0, ""))
        self.assertIn("올라갔지만 공개 확인은 아직 끝나지 않았습니다", out)
        self.assertIn(f"check-deploy {project_id}", out)
        self.assertEqual(self.status(project_id), st.PUSHED)
        data = self.data("check-deploy", project_id)
        self.assertEqual((data["status"], data["verified"]), (st.PUBLISHED, True))

    def test_a_push_that_failed_shows_the_next_steps_and_exit_one(self):
        project_id = self.approved()
        self.backend.push_errors = [AppError("GIT_PUSH_AUTH", detail="could not read Username")]
        out, err = self.fails("publish-pages", project_id, "--yes")
        for needle in ("코드: GIT_PUSH_AUTH", "저장소에 올릴 권한", "같은 명령을 다시 실행", "--cancel --yes"):
            self.assertIn(needle, err)
        self.assertEqual(self.status(project_id), st.COMMITTED)
        shown = self.ok("show", project_id)
        self.assertIn("이 PC 에 기록함(아직 안 올림)", shown)
        self.assertIn("--cancel --yes", shown)

    def test_cancelling_needs_yes_and_then_undoes_the_unpushed_record(self):
        project_id = self.approved()
        self.backend.push_errors = [AppError("GIT_PUSH_NETWORK")]
        self.fails("publish-pages", project_id, "--yes")
        calls = len(self.backend.calls)
        _out, err = self.fails("publish-pages", project_id, "--cancel")
        self.assertIn("CONFIRMATION_REQUIRED", err)
        self.assertEqual(len(self.backend.calls), calls)
        out = self.ok("publish-pages", project_id, "--cancel", "--yes")
        self.assertIn("올리지 않은 글 기록을 되돌렸습니다", out)
        self.assertEqual(self.status(project_id), st.PUBLISH_FAILED)
        self.assertIn("PUBLISH_CANCELLED", self.ok("show", project_id))

    def test_the_next_step_hints_follow_the_state(self):
        project_id = self.new_post()
        self.assertIn("preview", self.ok("show", project_id))
        self.ok("review", project_id, "--platform", "pages", *PAGES)
        self.assertIn("approve", self.ok("show", project_id))
        self.ok("approve", project_id, "--platform", "pages")
        self.assertIn("publish-pages", self.ok("show", project_id))
        self.ok("publish-pages", project_id, "--yes", "--no-wait")
        self.assertIn("check-deploy", self.ok("show", project_id))


class NaverCommandsTest(Base):
    def setUp(self):
        super().setUp()
        self.profile_args = lambda blog, name, tag: ["naver-profile", "set", blog, "--name", name, "--url", f"https://blog.naver.com/example{blog[-1]}{blog[-1]}{blog[-1]}", "--tags", tag, "--min-chars", "10"]

    def test_profiles_are_set_shown_and_validated(self):
        self.assertIn("프로필이 없습니다", self.ok("naver-profile", "show"))
        self.assertIn("블로그 에이 프로필을 저장했습니다", self.ok(*self.profile_args("naver_a", "블로그 에이", "생활")).replace("네이버 A", "블로그 에이"))
        self.assertIn("블로그 에이", self.ok("naver-profile", "show"))
        self.assertEqual(self.data("naver-profile", "show")["profiles"]["naver_a"]["default_tags"], ["생활"])
        self.ok("naver-profile", "set", "naver_a", "--tone", "차분하게", "--category-map", "경제=경제 이야기", "--forbidden", "광고,협찬")
        profile = self.data("naver-profile", "show")["profiles"]["naver_a"]
        self.assertEqual((profile["tone"], profile["categories"], profile["forbidden_phrases"], profile["display_name"]), ("차분하게", [["경제", "경제 이야기"]], ["광고", "협찬"], "블로그 에이"))
        self.fails("naver-profile", "set", "naver_b", "--tone", "이름 없이")
        self.fails("naver-profile", "set", "naver_a", "--url", "https://example.com/not-naver")
        _out, err = self.fails("naver-profile", "set", code=2)
        self.assertIn("블로그 구분", err)
        _out, err = self.fails("naver-profile", "set", "naver_a", "--category-map", "분류만", code=2)
        self.assertIn("원고분류=네이버카테고리", err)

    def test_review_issue_and_record_the_published_address(self):
        self.ok(*self.profile_args("naver_a", "블로그 에이", "생활"))
        project_id = self.new_post()
        review = self.ok("review", project_id, "--platform", "naver_a")
        self.assertIn("검토 중으로 보냈습니다", review)
        self.assertIn("naver-package", review)
        issued = self.ok("naver-package", project_id, "--blog", "naver_a")
        for needle in ("복사용 글입니다", "직접 붙여 넣어 발행하세요", "[제목]", "[본문]", "[태그]", "#생활", "[발행 전 체크리스트]", "naver-done"):
            self.assertIn(needle, issued)
        self.assertEqual(self.status(project_id, "naver_a"), st.READY_TO_COPY)
        done = self.ok("naver-done", project_id, "--blog", "naver_a", "--url", "https://blog.naver.com/examplea/223000000001")
        self.assertIn("직접 발행함", done)
        self.assertEqual(self.status(project_id, "naver_a"), st.PUBLISHED_MANUAL)
        _out, err = self.fails("naver-done", project_id, "--blog", "naver_a", "--url", "https://example.com/x")
        self.assertIn("STATUS_TRANSITION_INVALID", err, "이미 발행한 글의 주소는 다시 기록하지 않는다")

    def test_two_nearly_identical_blogs_need_the_flag_and_the_error_lists_the_reasons(self):
        self.ok(*self.profile_args("naver_a", "블로그 에이", "생활"))
        self.ok(*self.profile_args("naver_b", "블로그 비", "정보"))
        project_id = self.new_post()
        self.ok("review", project_id, "--platform", "naver_a")
        both = self.ok("preview", project_id, "--platform", "naver")
        self.assertIn("많이 비슷함 — 직접 승인이 필요합니다", both)
        self.ok("review", project_id, "--platform", "naver_b")
        for argv in (("naver-package", project_id, "--blog", "naver_a"), ("approve", project_id, "--platform", "naver_a")):
            with self.subTest(argv=argv[0]):
                _out, err = self.fails(*argv)
                self.assertIn("코드: NAVER_SIMILARITY_HIGH", err)
                self.assertIn("걸린 항목:", err)
                self.assertEqual(self.status(project_id, "naver_a"), st.REVIEW_REQUIRED)
        self.assertIn("복사용 글입니다", self.ok("naver-package", project_id, "--blog", "naver_a", "--similarity-approved"))
        self.assertEqual(self.status(project_id, "naver_a"), st.READY_TO_COPY)

    def test_approve_for_naver_gives_the_ready_to_copy_state_and_the_next_command(self):
        self.ok(*self.profile_args("naver_a", "블로그 에이", "생활"))
        project_id = self.new_post()
        self.ok("review", project_id, "--platform", "naver_a")
        out = self.ok("approve", project_id, "--platform", "naver_a")
        self.assertIn("복사 준비를 마쳤습니다", out)
        self.assertIn("naver-package", out)
        self.assertIn("승인을 거뒀습니다", self.ok("revoke", project_id, "--platform", "naver_a"))

    def test_per_blog_text_comes_from_the_options_and_the_ai_notice_can_be_left_out(self):
        self.ok(*self.profile_args("naver_a", "블로그 에이", "생활"))
        project_id = self.new_post()
        body = self.tmp / "에이용.md"
        body.write_text(ss.DIFFERENT, encoding="utf-8")
        self.ok("review", project_id, "--platform", "naver_a", "--title", "에이용 제목", "--body-file", str(body), "--no-ai-disclosure", "--tags", "산책")
        issued = json.loads(self.ok("--json", "naver-package", project_id, "--blog", "naver_a"))["data"]
        self.assertEqual(issued["package"]["title"], "에이용 제목")
        self.assertIn("산책", issued["package"]["tags"])
        self.assertNotIn("AI 도구의 도움", issued["copy_text"])

    def test_without_a_profile_the_command_says_how_to_set_one(self):
        project_id = self.new_post()
        _out, err = self.fails("review", project_id, "--platform", "naver_a")
        self.assertIn("코드: NAVER_PROFILE_MISSING", err)
        self.assertIn("naver-profile set", err)


class StorageAndSetupTest(Base):
    def test_backup_and_restore_through_the_command_line(self):
        project_id = self.new_post("지킬 글")
        out = self.ok("backup")
        self.assertIn("백업을 만들었습니다", out)
        self.ok("delete", project_id, "--yes")
        restored = self.ok("restore", "--latest", "--yes")
        self.assertIn("백업으로 되돌렸습니다", restored)
        self.assertIn("직전의 상태는 따로 백업", restored)
        self.assertEqual([row["title"] for row in self.data("list")["projects"]], ["지킬 글"])
        _out, err = self.fails("restore", code=2)
        self.assertIn("--latest", err)
        self.fails("restore", str(self.tmp / "없음.db"), "--latest", code=2)
        self.fails("restore", str(self.tmp / "없음.db"), "--yes")

    def test_connect_remembers_the_folder_only_in_the_settings_file(self):
        out = self.ok("connect", str(self.tmp / "chanceblog"))
        self.assertIn("연결했습니다", out)
        self.assertEqual(self.ctx.settings.repo_path(), str(self.tmp / "chanceblog"))
        self.assertIn("설정 파일에만 기억합니다", out)

    def test_a_folder_that_is_not_chanceblog_is_not_remembered(self):
        self.ctx.settings.save_repo_path("이전 연결")
        self.backend.inspect_error = AppError("PAGES_LOCAL_REPO_INVALID", detail="origin 이 chanceblog 가 아니다")
        _out, err = self.fails("connect", str(self.tmp / "other"))
        self.assertIn("PAGES_LOCAL_REPO_INVALID", err)
        self.assertEqual(self.ctx.settings.repo_path(), "이전 연결")

    def test_a_relative_folder_is_remembered_as_an_absolute_path(self):
        old = os.getcwd()
        os.chdir(self.tmp)
        self.addCleanup(os.chdir, old)
        self.ok("connect", "chanceblog")
        saved = Path(self.ctx.settings.repo_path())
        self.assertTrue(saved.is_absolute())
        self.assertEqual(os.path.normcase(os.path.realpath(saved)), os.path.normcase(os.path.realpath(self.tmp / "chanceblog")))

    def test_doctor_prints_the_results_and_the_exit_code_follows_the_failures(self):
        out = self.ok("doctor")
        self.assertIn("점검 결과:", out)
        self.assertIn("[정상] 프로그램 버전", out)
        self.backend.inspect_error = AppError("PAGES_LOCAL_REPO_DIRTY")
        code, out, err = self.cli("doctor")
        self.assertEqual((code, err), (1, ""))
        self.assertIn("[실패] 연결한 chanceblog 저장소", out)
        self.assertIn("오류 코드 PAGES_LOCAL_REPO_DIRTY", out)
        self.assertIn("하실 일:", out)
        payload = json.loads(self.cli("--json", "doctor")[1])
        self.assertEqual((payload["ok"], payload["command"]), (False, "doctor"))
        self.assertTrue(any(item["code"] == "PAGES_LOCAL_REPO_DIRTY" for item in payload["data"]["checks"]))

    def test_doctor_online_checks_the_push_permission(self):
        self.ok("doctor", "--online")
        self.assertEqual(self.backend.count("check_push_access"), 1)

    def test_the_data_folder_and_repository_come_from_the_flags_and_the_environment(self):
        env = {"CHANCEBLOG_DESKTOP_DATA": str(self.tmp / "from_env")}
        out, err = io.StringIO(), io.StringIO()
        self.assertEqual(cli.main(["new", "--title", "환경 변수 글", "--text", "본문"], out=out, err=err, env=env), 0, err.getvalue())
        self.assertTrue((self.tmp / "from_env" / "chanceblog.db").is_file())
        out = io.StringIO()
        self.assertEqual(cli.main(["--data-dir", str(self.tmp / "from_flag"), "new", "--title", "플래그 글", "--text", "본문"], out=out, err=err, env=env), 0, err.getvalue())
        self.assertTrue((self.tmp / "from_flag" / "chanceblog.db").is_file())
        out = io.StringIO()
        cli.main(["--json", "list"], out=out, err=err, env=env)
        self.assertEqual([row["title"] for row in json.loads(out.getvalue())["data"]["projects"]], ["환경 변수 글"])


class MaskingTest(Base):
    def assert_masked(self, text):
        self.assertNotIn(ss.KEY, text)

    def test_a_key_in_the_manuscript_or_title_never_appears_in_any_output(self):
        project_id = self.new_post(title=f"제목 {ss.KEY}", text=ss.ko_text(extra=f"실수로 {ss.KEY} 를 붙였습니다."))
        shown = self.ok("show", project_id, "--full")
        self.assert_masked(shown)
        self.assertIn("[가림: Google API 키]", shown)
        self.assert_masked(self.ok("list"))
        for argv in (("--json", "show", project_id, "--full"), ("--json", "list")):
            out = self.ok(*argv)
            self.assert_masked(out)
            json.loads(out)                                  # 가린 뒤에도 JSON 이 깨지지 않는다
        self.assertIn("[가림:", self.ok("--json", "show", project_id, "--full"))

    def test_a_key_in_a_review_preview_and_in_the_gate_errors_is_hidden_too(self):
        project_id = self.new_post(text=ss.ko_text(extra=f"실수로 {ss.KEY} 를 붙였습니다."))
        self.assert_masked(self.ok("preview", project_id, "--platform", "pages", *PAGES, "--full"))
        self.assert_masked(self.ok("review", project_id, "--platform", "pages", *PAGES))
        out, err = self.fails("approve", project_id, "--platform", "pages")
        self.assert_masked(out + err)
        self.assertIn("SECRET_IN_TEXT_BLOCKED", err)
        code, out, err = self.cli("--json", "approve", project_id, "--platform", "pages")
        self.assert_masked(out + err)
        self.assertEqual(json.loads(out)["error"]["code"], "SECRET_IN_TEXT_BLOCKED")

    def test_a_key_in_an_error_detail_from_git_is_hidden_in_text_and_json_and_verbose_lines(self):
        project_id = self.approved()
        self.backend.push_errors = [AppError("GIT_PUSH_AUTH", detail=f"remote: https://user:{ss.KEY}@github.com/x failed")]
        out, err = self.fails("--verbose", "publish-pages", project_id, "--yes")
        self.assert_masked(out + err)
        self.backend.push_errors = [AppError("GIT_PUSH_AUTH", detail=f"remote: token {ss.KEY}")]
        code, out, err = self.cli("--json", "publish-pages", project_id, "--yes")
        self.assert_masked(out + err)
        self.assertEqual(json.loads(out)["error"]["code"], "GIT_PUSH_AUTH")

    def test_an_environment_secret_is_never_read_or_printed(self):
        env = {"GEMINI_API_KEY": ss.KEY, "GITHUB_TOKEN": ss.KEY, "CHANCEBLOG_DESKTOP_DATA": str(self.tmp / "d")}
        out, err = io.StringIO(), io.StringIO()
        for argv in (["new", "--title", "글", "--text", "본문"], ["list"], ["--verbose", "show", "ffffffff"], ["--json", "doctor"]):
            cli.main(argv, out=out, err=err, env=env)
        self.assert_masked(out.getvalue() + err.getvalue())

    def test_a_secret_in_the_publish_text_blocks_the_publish_and_nothing_is_written(self):
        project_id = self.approved()
        with self.ctx.store() as store:
            project = store.load(project_id)
            project.variants["github_pages"].rendered += f"\n{ss.KEY}\n"
            store.save(project)
        out, err = self.fails("publish-pages", project_id, "--yes")
        self.assertIn("SECRET_IN_TEXT_BLOCKED", err)
        self.assert_masked(out + err)
        self.assertEqual(self.backend.count("commit"), 0)


class JsonShapeTest(Base):
    def test_every_command_prints_an_ok_command_data_object(self):
        project_id = self.new_post()
        ss.naver_profiles(self.ctx, both=False)
        cases = (("list",), ("show", project_id), ("preview", project_id, "--platform", "pages", *PAGES), ("preview", project_id, "--platform", "naver"),
                 ("review", project_id, "--platform", "pages", *PAGES), ("approve", project_id, "--platform", "pages"), ("publish-pages", project_id), ("naver-profile", "show"),
                 ("backup",), ("doctor",), ("revoke", project_id, "--platform", "pages"))
        for argv in cases:
            with self.subTest(argv=argv[0]):
                code, out, err = self.cli("--json", *argv)
                self.assertEqual((code, err), (0, ""))
                payload = json.loads(out)
                self.assertEqual((payload["ok"], payload["command"], sorted(payload)), (True, argv[0], ["command", "data", "ok"]))
                self.assertIsInstance(payload["data"], dict)

    def test_the_publish_report_json_has_the_fields_a_program_needs(self):
        project_id = self.approved()
        data = self.data("publish-pages", project_id, "--yes")
        self.assertEqual((data["status"], data["verified"], data["pending_verification"], data["url"], data["dry_run"]), (st.PUBLISHED, True, False, ss.KO_URL, False))
        self.assertEqual(data["plan"]["path"], ss.KO_PATH)
        self.assertNotIn("text", data["plan"])

    def test_a_failed_doctor_is_not_ok_and_still_prints_its_checks(self):
        self.backend.inspect_error = AppError("PAGES_LOCAL_REPO_NOT_MAIN")
        code, out, err = self.cli("--json", "doctor")
        payload = json.loads(out)
        self.assertEqual((code, payload["ok"]), (1, False))
        self.assertGreater(len(payload["data"]["checks"]), 8)


class RealProcessTest(unittest.TestCase):
    """실제로 프로세스를 띄워 본다 — 진입점(`__main__`)·한글 출력·종료 코드."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.env = {**ss.env_without_repo(), "PYTHONPATH": str(ss.ROOT / "src"), "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1"}

    def run_module(self, *argv, **kwargs):
        done = subprocess.run([sys.executable, "-X", "utf8", "-m", "chanceblog_desktop", *argv], capture_output=True, env=self.env, cwd=self.tmp, **kwargs)
        return done.returncode, done.stdout.decode("utf-8"), done.stderr.decode("utf-8")

    def test_help_runs_prints_korean_and_exits_zero(self):
        code, out, err = self.run_module("--help")
        self.assertEqual((code, err), (0, ""))
        self.assertIn("publish-pages", out)
        self.assertIn("기본이 미리 보기", out)

    def test_a_usage_error_exits_two_without_a_traceback(self):
        code, out, err = self.run_module("nosuchcommand")
        self.assertEqual((code, out), (2, ""))
        self.assertIn("사용법 오류", err)
        self.assertNotIn("Traceback", err)

    def test_a_small_session_in_a_temporary_data_folder(self):
        data = str(self.tmp / "데이터")
        code, out, err = self.run_module("--data-dir", data, "new", "--title", "프로세스 글", "--text", "본문 첫 문단입니다.")
        self.assertEqual((code, err), (0, ""), err)
        self.assertIn("글을 만들었습니다", out)
        code, out, err = self.run_module("--data-dir", data, "--json", "list")
        self.assertEqual((code, err), (0, ""))
        self.assertEqual([row["title"] for row in json.loads(out)["data"]["projects"]], ["프로세스 글"])
        code, out, err = self.run_module("--data-dir", data, "publish-pages", "ffffffff")
        self.assertEqual((code, out), (1, ""))
        self.assertIn("코드: CONTENT_NOT_FOUND", err)
        self.assertNotIn("Traceback", err)

    @unittest.skipUnless(ss.HAVE_GIT, "git 이 필요하다")
    def test_doctor_runs_for_real_and_changes_nothing(self):
        data = self.tmp / "d"
        code, out, err = self.run_module("--data-dir", str(data), "doctor")
        self.assertEqual((code, err), (0, ""), out + err)
        for needle in ("[정상] 프로그램 버전", "[정상] git", "[정상] 핵심 코드(vendor/)", "[주의] 연결한 chanceblog 저장소"):
            self.assertIn(needle, out)
        self.assertFalse(data.exists(), "점검은 아무것도 만들지 않는다")

    def test_the_data_folder_inside_the_programs_own_folder_is_refused(self):
        code, out, err = self.run_module("--data-dir", str(ss.ROOT / "userdata_for_test"), "list")
        self.assertEqual((code, out), (1, ""))
        self.assertIn("DATA_DIR_UNSAFE", err)
        self.assertFalse((ss.ROOT / "userdata_for_test").exists())


if __name__ == "__main__":
    unittest.main()
