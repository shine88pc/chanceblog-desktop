"""서비스 층·명령줄 — 독립 검증이 재현한 빈틈을 막는 시험.

지키는 것:
  1) **여러 줄에 걸친 비밀은 어느 출력에서도 새지 않는다**: 개인 키 블록·다음 줄에 이어지는 값·여러 줄 JSON 이 원고에 있어도 미리 보기(기본·`--full`)·검토·`show --full`·`--json` 에서 본문 줄이 그대로 나가지 않는다.
  2) 명령줄 옵션을 줄여 쓸 수 없다(`--y`·`--ye` 가 `--yes` 로 읽혀 실제로 올라가는 일이 없다 — 사용법 오류, 종료 코드 2, 아무 일도 안 일어남).
  3) 도움말·사용법은 한국어다(`usage:`·`positional arguments:`·`options:`·`show this help message and exit` 가 없다). 오류 문구의 상태 이름은 한국어 뜻과 함께 보인다.
  4) `delete` 는 `--yes` 가 없으면 어느 글인지(제목·번호·상태)를 보여 주고 지우지 않으며, 지울 때는 먼저 백업한다.
  5) 큰 입력·NUL 든 원고·현재 저장소 파일 자체를 복구하려는 것·내용이 깨진 백업은 거절하고, 복구 직전 사본은 같은 초에 두 번 해도 덮어쓰지 않는다.
  6) **동작으로 확인**: 모든 명령을 가짜 backend 로 `--yes` 없이 돌려 commit·push·되돌리기가 한 번도 불리지 않는다(소스 모양을 보는 안전 시험을 우회하는 코드도 걸린다).
"""
import io
import json
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
from chanceblog_desktop.service import cli, pages_flow, projects  # noqa: E402
from chanceblog_desktop.service.backend import GitPagesBackend  # noqa: E402

PEM_BODY = ("MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQC7VJTUt9Us8cKj", "MBtjkL5kdPLXFgTPtc5s4yRZ2ZK3L0cDdZ0Fjd1Zr9pSxY2Gm0t8Wm2rYh3nQb1o", "Zm9vYmFyYmF6cXV4Zm9vYmFyYmF6cXV4Zm9vYmFyYmF6cXV4Zm9vYmFyYmF6cXV4")
# 저장소의 비밀 검사(test_repo_layout)가 이 파일을 키로 오인하지 않게 조각으로 이어 붙여 만든다
PEM = "-----BEGIN " + "PRIVATE KEY-----\n" + "\n".join(PEM_BODY) + "\n-----END " + "PRIVATE KEY-----"
GOOGLE_SECRET = "GOC" + "SPX-" + "abcdefghijklmnopqrstuvwxyz012345"
SERVICE_JSON = '{\n  "type": "service_account",\n  "client_' + 'secret":\n     "' + GOOGLE_SECRET + '",\n  "pass' + 'word":\n     "hunter2hunter2hunter2"\n}'
SECRET_PIECES = PEM_BODY + (GOOGLE_SECRET, "hunter2hunter2hunter2")


def new_ctx():
    tmp = tempfile.TemporaryDirectory()
    ctx = ss.make_ctx(tmp.name, backend=ss.FakeBackend())
    return tmp, ctx


class Base(unittest.TestCase):
    def setUp(self):
        tmp, self.ctx = new_ctx()
        self.addCleanup(tmp.cleanup)
        self.backend = self.ctx.backend

    def run_cli(self, *argv):
        return ss.run_cli(self.ctx, *argv)

    def pages_args(self):
        return ("--platform", "pages", "--category", "경제·일", "--lang", "ko", "--image-url", "https://images.example.invalid/a.jpg")


class MultiLineSecretTest(Base):
    def project_with_secrets(self):
        body = "서두 문장입니다. 아래는 실수로 붙여 넣은 것입니다.\n\n" + PEM + "\n\n" + SERVICE_JSON + "\n\n" + ss.ko_text(1500)
        return projects.new_project(self.ctx, "비밀이 든 글", body).project_id

    def assert_no_secret(self, label, *outputs):
        text = "\n".join(outputs)
        for piece in SECRET_PIECES:
            self.assertNotIn(piece, text, f"{label}: 비밀 조각이 그대로 나갔다: {piece[:20]}")

    def test_no_text_or_json_output_leaks_a_secret_that_spans_several_lines(self):
        project_id = self.project_with_secrets()
        commands = (("preview",) + self.pages_args(), ("preview",) + self.pages_args() + ("--full",), ("review",) + self.pages_args(), ("show", "--full"), ("show",), ("approve", "--platform", "pages"),
                    ("publish-pages",), ("list",), ("edit",))
        for flags in commands:
            for as_json in (False, True):
                with self.subTest(command=flags[0], full="--full" in flags, json=as_json):
                    argv = [flags[0], project_id, *flags[1:]] + (["--json"] if as_json else [])
                    code, out, err = self.run_cli(*argv)
                    self.assert_no_secret(f"{flags[0]} json={as_json}", out, err)
                    if flags[0] == "preview" and not as_json:
                        self.assertIn("[가림", out, "가렸다는 표시가 있다")

    def test_an_error_that_quotes_the_text_is_masked_as_a_whole_too(self):
        project_id = self.project_with_secrets()
        self.run_cli("review", project_id, *self.pages_args())
        code, out, err = self.run_cli("approve", project_id, "--platform", "pages")
        self.assertEqual(code, 1)
        self.assertIn("SECRET_IN_TEXT_BLOCKED", err)
        self.assert_no_secret("approve", out, err)

    def test_mask_block_hides_a_key_block_and_a_value_on_the_next_line(self):
        masked = cli.mask_block("앞 줄\n" + PEM + "\n뒷 줄\npassword:\n   hunter2hunter2hunter2\n")
        self.assertNotIn(PEM_BODY[0], masked)
        self.assertNotIn("hunter2hunter2hunter2", masked)
        self.assertIn("앞 줄", masked)
        self.assertIn("뒷 줄", masked)
        self.assertEqual(cli.mask_block(masked), masked, "이미 가린 글을 다시 가려도 같다")

    def test_a_very_long_output_is_masked_in_pieces_without_cutting_a_key_block_in_two(self):
        filler = "에너지 절약은 작은 습관에서 시작됩니다.\n" * 8000                      # 약 10만 자 — 한 번에 가릴 수 있는 한도(20만)의 절반을 넘긴다
        text = filler + PEM + "\n" + filler + "맨 끝 표시"
        self.assertGreater(len(text), 2 * 100_000)
        masked = cli.mask_block(text)
        for piece in PEM_BODY:
            self.assertNotIn(piece, masked)
        self.assertIn("맨 끝 표시", masked, "나눠 가려도 끝까지 나간다")
        begin = PEM.split("\n")[0]
        head = "x" * (99_988 - len(begin)) + "\n"                              # 개인 키 블록의 첫 본문 줄에서 나누는 한도(10만 자)를 넘게 맞춘다 — 열린 블록 안에서 끊으면 나머지 본문 줄이 새 덩어리에서 가려지지 않는다
        crossing = head + PEM + "\n" + "가" * 150_000
        self.assertGreater(len(crossing), 200_000)
        masked_crossing = cli.mask_block(crossing)
        for piece in PEM_BODY:
            self.assertNotIn(piece, masked_crossing, "한도가 키 블록 한가운데에 걸려도 블록 전체가 가려진다")

    def test_error_lines_and_usage_errors_are_masked_as_blocks_too(self):
        out, err = io.StringIO(), io.StringIO()
        code = cli.main(["show", "없는글번호가" + PEM], out=out, err=err, ctx=self.ctx)
        self.assertEqual(code, 1)
        self.assert_no_secret("오류", out.getvalue(), err.getvalue())


class AbbreviationTest(Base):
    def approved(self):
        project_id = ss.make_approved(self.ctx)
        self.backend.calls.clear()
        return project_id

    def test_a_shortened_confirmation_flag_is_a_usage_error_and_nothing_happens(self):
        project_id = self.approved()
        for flag in ("--y", "--ye", "--ye=1", "--yes1", "--ca", "--no-w", "--wa"):
            with self.subTest(flag=flag):
                code, out, err = self.run_cli("publish-pages", project_id, flag)
                self.assertEqual(code, 2, (flag, out, err))
                self.assertIn("사용법 오류", err)
                self.assertEqual(self.backend.calls, [], "저장소를 들여다보지도 않았다")
                self.assertEqual(ss.status_of(self.ctx, project_id), st.APPROVED)

    def test_the_cancel_and_delete_confirmations_cannot_be_shortened_either(self):
        project_id = self.approved()
        for argv in (("publish-pages", project_id, "--cancel", "--y"), ("delete", project_id, "--y"), ("delete", project_id, "--ye"), ("restore", "--lat")):
            with self.subTest(argv=argv):
                self.assertEqual(self.run_cli(*argv)[0], 2)
        self.assertEqual(len(projects.list_projects(self.ctx)), 1, "아무것도 지워지지 않았다")

    def test_common_options_cannot_be_shortened_in_front_of_or_after_the_command(self):
        for argv in (("--js", "list"), ("list", "--js"), ("--dat", "x", "list"), ("--rep", "x", "list"), ("--verb", "list")):
            with self.subTest(argv=argv):
                code, out, err = self.run_cli(*argv)
                self.assertEqual(code, 2, (argv, out, err))

    def test_the_full_spellings_still_work(self):
        project_id = self.approved()
        self.assertEqual(self.run_cli("publish-pages", project_id, "--yes", "--no-wait", "--wait", "30")[0], 0)
        self.assertEqual(self.backend.count("commit"), 1)
        self.assertEqual(self.run_cli("list", "--json")[0], 0)


class KoreanHelpTest(Base):
    ENGLISH = ("usage:", "positional arguments", "options:", "optional arguments", "show this help message and exit")

    def test_every_help_screen_is_korean(self):
        names = [None] + sorted(cli.build_parser()._subparsers._group_actions[0].choices)
        for name in names:
            with self.subTest(command=name or "(처음)"):
                code, out, err = self.run_cli(*([name] if name else []), "--help")
                self.assertEqual((code, err), (0, ""), err)
                self.assertIn("사용법:", out)
                self.assertIn("옵션", out)
                self.assertIn("이 도움말을 보여 주고 끝냅니다", out)
                for word in self.ENGLISH:
                    self.assertNotIn(word, out)

    def test_positional_arguments_have_a_korean_title_and_short_help_flag_works(self):
        code, out, err = self.run_cli("show", "-h")
        self.assertEqual(code, 0)
        self.assertIn("위치 인자", out)
        self.assertIn("글번호", out)

    def test_usage_errors_are_korean(self):
        for argv in (("show",), ("show", "x", "--nope"), ("review", "x", "--platform", "zzz"), ("publish-pages", "x", "--wait", "abc"), ("list", "--data-dir")):
            with self.subTest(argv=argv):
                code, out, err = self.run_cli(*argv)
                self.assertEqual(code, 2)
                self.assertIn("사용법 오류", err)
                for word in ("the following", "unrecognized", "invalid choice", "expected one argument", "invalid int"):
                    self.assertNotIn(word, err)


class StatusNamesInErrorsTest(Base):
    def test_the_status_names_in_the_error_text_come_with_their_korean_meaning(self):
        fresh = projects.new_project(self.ctx, "새 글", ss.ko_text()).project_id
        code, out, err = self.run_cli("publish-pages", fresh, "--yes")
        self.assertEqual(code, 1)
        self.assertIn("시작 전 (NOT_STARTED)", err)
        self.assertIn("(COMMITTED)", err)
        code, out, err = self.run_cli("publish-pages", fresh, "--yes", "--json")
        payload = json.loads(out)
        self.assertIn("시작 전 (NOT_STARTED)", payload["error"]["message"])
        self.assertEqual(payload["error"]["code"], "STATUS_TRANSITION_INVALID")

    def test_the_error_object_itself_keeps_the_plain_status_names_for_programs(self):
        fresh = projects.new_project(self.ctx, "새 글", ss.ko_text()).project_id
        error = ss.code_of(pages_flow.run_pages_publish, self.ctx, fresh, confirmed=True)
        self.assertEqual(error.slots["현재 상태"], st.NOT_STARTED)


class DeletePreviewTest(Base):
    def test_delete_without_yes_names_the_post_and_deletes_nothing(self):
        view = projects.new_project(self.ctx, "지울 뻔한 글", ss.ko_text())
        project_id = ss.make_approved(self.ctx, title="승인한 글")
        for argv in (("delete", view.project_id), ("delete", project_id[:8])):
            with self.subTest(argv=argv):
                code, out, err = self.run_cli(*argv)
                self.assertEqual(code, 1)
                self.assertIn("CONFIRMATION_REQUIRED", err)
                self.assertIn("--yes", err)
        code, out, err = self.run_cli("delete", project_id[:8])
        self.assertIn("승인한 글", err)
        self.assertIn(project_id[:8], err)
        self.assertIn("승인됨 (APPROVED)", err)
        code, out, err = self.run_cli("delete", view.project_id)
        self.assertIn("지울 뻔한 글", err)
        self.assertIn("아직 어느 곳에도 내보내지 않음", err)
        self.assertEqual(len(projects.list_projects(self.ctx)), 2, "아무것도 지우지 않았다")
        self.assertFalse((self.ctx.workspace.backups_dir / "before-delete").exists(), "미리 보기는 백업도 만들지 않는다")

    def test_delete_of_a_post_that_does_not_exist_says_so_instead_of_asking_for_confirmation(self):
        code, out, err = self.run_cli("delete", "없는번호1234")
        self.assertEqual(code, 1)
        self.assertIn("CONTENT_NOT_FOUND", err)

    def test_delete_with_yes_backs_up_first_and_tells_where(self):
        view = projects.new_project(self.ctx, "지울 글", ss.ko_text())
        code, out, err = self.run_cli("delete", view.project_id, "--yes")
        self.assertEqual((code, err), (0, ""))
        self.assertIn("글을 지웠습니다", out)
        self.assertIn("지우기 직전 상태를 백업해 두었습니다", out)
        self.assertEqual(len(list((self.ctx.workspace.backups_dir / "before-delete").iterdir())), 1)


class InputLimitsTest(Base):
    def test_a_manuscript_with_a_nul_character_or_over_two_megabytes_is_refused(self):
        for text, why in (("본문\x00끝", "NUL"), ("가" * (700_000), "2MB 초과(한글 3바이트)"), ("a" * (2 * 1024 * 1024 + 1), "2MB 초과(영문)")):
            with self.subTest(why=why):
                error = ss.code_of(projects.new_project, self.ctx, "제목", text)
                self.assertEqual(error.code, "CONTENT_INVALID")
                self.assertIn(error.detail.split("(")[0].strip()[:3] and error.detail, error.detail)
        self.assertEqual(projects.list_projects(self.ctx), [])
        view = projects.new_project(self.ctx, "정상 글", "가" * 600_000)
        self.assertEqual(ss.code_of(projects.edit_project, self.ctx, view.project_id, markdown="x\x00y").code, "CONTENT_INVALID")
        self.assertEqual(ss.code_of(projects.import_html, self.ctx, "제목", "<p>a\x00b</p>").code, "CONTENT_INVALID")

    def test_the_file_reader_itself_refuses_over_five_megabytes_and_accepts_three(self):
        folder = Path(self.ctx.workspace.root)
        folder.mkdir(parents=True, exist_ok=True)
        three, six = folder / "three.md", folder / "six.md"
        three.write_bytes(b"a" * (3 * 1024 * 1024))
        six.write_bytes(b"a" * (5 * 1024 * 1024 + 1))
        self.assertEqual(len(cli.read_text_file(three)), 3 * 1024 * 1024)
        error = ss.code_of(cli.read_text_file, six)
        self.assertEqual(error.code, "CONTENT_INVALID")
        self.assertIn("너무 크다", error.detail)

    def test_an_input_file_over_five_megabytes_is_refused_without_being_read_whole(self):
        big = Path(self.ctx.workspace.root) / "big.md"
        big.parent.mkdir(parents=True, exist_ok=True)
        big.write_bytes(b"a" * (5 * 1024 * 1024 + 1))
        code, out, err = self.run_cli("new", "--title", "큰 글", "--file", str(big))
        self.assertEqual(code, 1)
        self.assertIn("CONTENT_INVALID", err)
        self.assertIn("너무 크다", err)
        small = big.parent / "small.md"
        small.write_text(ss.ko_text(), encoding="utf-8")
        self.assertEqual(self.run_cli("new", "--title", "작은 글", "--file", str(small))[0], 0)


class TextFileEncodingTest(Base):
    def write(self, name, data):
        folder = Path(self.ctx.workspace.root)
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / name
        path.write_bytes(data)
        return path

    def test_a_utf8_file_with_a_byte_order_mark_loses_the_mark(self):
        text = cli.read_text_file(self.write("bom.md", b"\xef\xbb\xbf" + "가나다 글".encode("utf-8")))
        self.assertEqual(text, "가나다 글")
        self.assertNotIn("\ufeff", text)

    def test_a_utf8_file_is_read_as_utf8_even_when_cp949_could_also_decode_its_bytes(self):
        latin = "Zoë café ñ ü ß"
        self.assertNotEqual(latin.encode("utf-8").decode("cp949"), latin, "이 글자들은 cp949 로도 읽히지만 다른 글자가 된다")
        self.assertEqual(cli.read_text_file(self.write("latin.md", latin.encode("utf-8"))), latin)

    def test_a_cp949_file_from_an_old_notepad_is_still_read(self):
        self.assertEqual(cli.read_text_file(self.write("old.md", "안녕하세요 글입니다".encode("cp949"))), "안녕하세요 글입니다")

    def test_a_file_that_is_neither_is_refused(self):
        for name, data in (("utf16.md", "글".encode("utf-16")), ("latin1.md", b"caf\xe9 \xff\xfe")):
            with self.subTest(file=name):
                self.assertEqual(ss.code_of(cli.read_text_file, self.write(name, data)).code, "CONTENT_INVALID")


class RestoreSafetyTest(Base):
    def test_restoring_the_live_store_file_itself_is_refused_at_once(self):
        projects.new_project(self.ctx, "글", ss.ko_text())
        live = self.ctx.workspace.store_path
        for spelling in (str(live), str(live).upper() if sys.platform == "win32" else str(live), str(Path(str(live).replace("chanceblog.db", "."))) + "/chanceblog.db"):
            with self.subTest(spelling=spelling):
                error = ss.code_of(projects.restore_store, self.ctx, spelling, confirmed=True)
                self.assertEqual(error.code, "CONTENT_INVALID")
                self.assertIn("글 저장소 파일 자체", error.detail)
        self.assertEqual(len(projects.list_projects(self.ctx)), 1)

    def test_a_backup_whose_posts_are_damaged_is_not_restored_and_the_current_data_stays(self):
        view = projects.new_project(self.ctx, "지금 글", ss.ko_text())
        broken = projects.backup_store(self.ctx)
        with closing(sqlite3.connect(str(broken))) as db:
            db.execute("UPDATE projects SET data = ?", ("{깨짐",))
            db.commit()
        other = projects.new_project(self.ctx, "나중에 만든 글", ss.ko_text(1200))
        error = ss.code_of(projects.restore_store, self.ctx, broken, confirmed=True)
        self.assertEqual(error.code, "STORE_CORRUPT")
        self.assertIn("원래대로 돌렸다", error.detail)
        ids = sorted(row.project_id for row in projects.list_projects(self.ctx))
        self.assertEqual(ids, sorted([view.project_id, other.project_id]), "현재 글이 그대로다")
        self.assertEqual([row.error for row in projects.list_projects(self.ctx)], ["", ""])

    def test_restore_needs_the_confirmation_and_without_it_changes_nothing_and_names_the_backup(self):
        projects.new_project(self.ctx, "글", ss.ko_text())
        backup = projects.backup_store(self.ctx)
        projects.new_project(self.ctx, "백업 뒤에 만든 글", ss.ko_text(1200))
        before = self.ctx.workspace.store_path.read_bytes()
        for argv in (("restore", "--latest"), ("restore", str(backup))):
            with self.subTest(argv=argv):
                code, out, err = self.run_cli(*argv)
                self.assertEqual(code, 1)
                self.assertIn("CONFIRMATION_REQUIRED", err)
                self.assertIn(backup.name, err, "어느 백업으로 되돌리려는지 보여 준다")
                self.assertIn("--yes", err)
                self.assertIn("before-restore", err, "되돌리기 직전 상태를 따로 백업한다는 것도 알린다")
        self.assertEqual(self.ctx.workspace.store_path.read_bytes(), before, "확인 없이는 글 저장소를 한 바이트도 바꾸지 않는다")
        self.assertFalse((self.ctx.workspace.backups_dir / "before-restore").exists(), "사전 백업도 만들지 않았다")
        for confirmed in (False, None, "yes", 1):
            with self.subTest(confirmed=confirmed):
                self.assertEqual(ss.code_of(projects.restore_store, self.ctx, backup, confirmed=confirmed).code, "CONFIRMATION_REQUIRED")
        self.assertEqual(len(projects.list_projects(self.ctx)), 2)
        code, out, err = self.run_cli("restore", "--latest", "--yes")
        self.assertEqual((code, err), (0, ""))
        self.assertEqual([row.title for row in projects.list_projects(self.ctx)], ["글"])
        self.assertTrue(any((self.ctx.workspace.backups_dir / "before-restore").iterdir()), "되돌리기 직전 상태가 따로 남았다")

    def test_restore_without_a_backup_to_name_still_says_what_is_missing_before_asking_for_the_confirmation(self):
        code, out, err = self.run_cli("restore", "--latest")
        self.assertEqual(code, 1)
        self.assertIn("CONTENT_NOT_FOUND", err)
        code, out, err = self.run_cli("restore", str(self.ctx.workspace.store_path))
        self.assertEqual(code, 1)
        self.assertIn("CONTENT_INVALID", err)

    def test_two_restores_in_the_same_second_keep_both_safety_copies(self):
        projects.new_project(self.ctx, "글", ss.ko_text())
        backup = projects.backup_store(self.ctx)
        projects.restore_store(self.ctx, backup, confirmed=True)
        projects.new_project(self.ctx, "둘째", ss.ko_text(1200))
        projects.restore_store(self.ctx, backup, confirmed=True)
        kept = sorted((self.ctx.workspace.backups_dir / "before-restore").iterdir())
        self.assertEqual(len(kept), 2, "같은 초에 두 번 복구해도 앞의 사본을 덮어쓰지 않는다")


class NoSurpriseWritesTest(Base):
    """모든 명령을 `--yes` 없이 돌려 보고 commit·push·되돌리기가 한 번도 불리지 않는다 — 소스 모양을 보는 안전 시험(AST)이 별칭·getattr 로 우회돼도 이 시험은 동작을 본다."""

    GUARDED = ("commit", "push", "discard")

    def argv_table(self, ids):
        approved, committed, pushed, fresh = ids
        pages = ("--category", "경제·일", "--lang", "ko", "--image-url", "https://images.example.invalid/a.jpg")
        return {
            "doctor": ["doctor"], "connect": ["connect", str(self.ctx.repo_path())], "new": ["new", "--title", "새 글", "--text", ss.ko_text()], "import-html": ["import-html", "--title", "옛 글", "--text", "<p>안녕하세요</p>"],
            "list": ["list"], "show": ["show", approved], "edit": ["edit", fresh, "--title", "고친 제목"], "review": ["review", fresh, "--platform", "pages", *pages], "preview": ["preview", approved, "--platform", "pages", *pages],
            "approve": ["approve", fresh, "--platform", "pages"], "revoke": ["revoke", approved, "--platform", "pages"], "publish-pages": ["publish-pages", approved], "check-deploy": ["check-deploy", pushed],
            "naver-package": ["naver-package", fresh, "--blog", "naver_a"], "naver-done": ["naver-done", fresh, "--blog", "naver_a", "--url", "https://blog.naver.com/x/1"], "naver-profile": ["naver-profile", "show"],
            "backup": ["backup"], "restore": ["restore", "--latest"], "delete": ["delete", fresh], "candidates": ["candidates", "list"], "draft": ["draft", "plan", "1"],
        }

    def test_no_command_commits_pushes_or_undoes_anything_without_the_confirmation(self):
        approved = ss.make_approved(self.ctx, title="승인한 글")
        self.ctx.clock.advance(seconds=3)
        committed = ss.make_approved(self.ctx, title="올리다 멈춘 글")
        self.backend.push_errors = [AppError("GIT_PUSH_NETWORK")]
        with self.assertRaises(AppError):
            pages_flow.run_pages_publish(self.ctx, committed, confirmed=True)
        self.ctx.clock.advance(seconds=3)
        pushed = ss.make_approved(self.ctx, title="올린 글")
        pages_flow.run_pages_publish(self.ctx, pushed, confirmed=True, wait=False)
        fresh = projects.new_project(self.ctx, "아직 시작 전", ss.ko_text()).project_id
        projects.backup_store(self.ctx)
        self.backend.calls.clear()
        table = self.argv_table((approved, committed, pushed, fresh))
        commands = sorted(cli.build_parser()._subparsers._group_actions[0].choices)
        self.assertEqual(sorted(table), commands, "새 명령을 더했다면 이 표에도 더한다(그 명령도 확인 없이 아무것도 올리지 않아야 한다)")
        for name in commands:
            extras = [[]] if name != "publish-pages" else [[], ["--no-wait"], ["--cancel"], ["--wait", "5"], ["--cancel", "--no-wait"]]
            for extra in extras:
                with self.subTest(command=name, extra=extra):
                    self.run_cli(*table[name], *extra)
                    for guarded in self.GUARDED:
                        self.assertEqual(self.backend.count(guarded), 0, f"{name} {extra}: --yes 없이 {guarded} 가 불렸다")

    def test_with_the_confirmation_the_guarded_calls_do_happen_so_the_check_above_is_not_vacuous(self):
        approved = ss.make_approved(self.ctx)
        self.backend.calls.clear()
        self.assertEqual(self.run_cli("publish-pages", approved, "--yes", "--no-wait")[0], 0)
        self.assertEqual((self.backend.count("commit"), self.backend.count("push")), (1, 1))
        stuck = ss.make_approved(self.ctx, title="멈춘 글")
        self.ctx.clock.advance(seconds=2)
        stuck = ss.make_approved(self.ctx, title="멈춘 글 둘")
        self.backend.push_errors = [AppError("GIT_PUSH_NETWORK")]
        self.run_cli("publish-pages", stuck, "--yes")
        self.backend.calls.clear()
        self.assertEqual(self.run_cli("publish-pages", stuck, "--cancel", "--yes")[0], 0)
        self.assertEqual(self.backend.count("discard"), 1)


class RestoredPostIsNotPublishedTwiceTest(Base):
    def test_a_post_whose_identical_text_is_already_online_is_refused_before_anything_is_written(self):
        project_id = ss.make_approved(self.ctx)
        self.backend.calls.clear()
        self.backend.same_content_found = ["_posts/경제·일/2026-11-02-KR-103012.md"]
        self.ctx.clock.advance(hours=1)
        for call in (lambda: pages_flow.plan_pages_publish(self.ctx, project_id), lambda: pages_flow.run_pages_publish(self.ctx, project_id, confirmed=True)):
            error = ss.code_of(call)
            self.assertEqual(error.code, "DUPLICATE_CONTENT")
            self.assertIn("103012", error.slots["파일"])
        code, out, err = self.run_cli("publish-pages", project_id)
        self.assertEqual(code, 1)
        self.assertIn("DUPLICATE_CONTENT", err)
        self.assertEqual((self.backend.count("commit"), self.backend.count("push")), (0, 0))
        self.assertEqual(ss.status_of(self.ctx, project_id), st.APPROVED)


class WaitAndProgressTest(Base):
    def test_the_wait_time_has_an_upper_bound_and_must_be_a_number(self):
        project_id = ss.make_approved(self.ctx)
        self.backend.calls.clear()
        for value in ("21601", "-1", "abc", "99999999999", "1.5"):
            with self.subTest(wait=value):
                code, out, err = self.run_cli("publish-pages", project_id, "--wait", value)
                self.assertEqual(code, 2, (value, out, err))
                self.assertIn("사용법 오류", err)
                self.assertNotIn("argument", err)
                code, out, err = self.run_cli("check-deploy", project_id, "--wait", value)
                self.assertEqual(code, 2)
        self.assertEqual(self.backend.calls, [])
        for value in ("0", "21600", "720"):
            with self.subTest(wait=value):
                self.assertEqual(self.run_cli("publish-pages", project_id, "--wait", value)[0], 0)

    def test_the_wait_progress_is_told_on_the_error_stream_each_time_it_waits(self):
        backend = GitPagesBackend(git=lambda cwd, args, timeout=0, input_bytes=None: None, expected_origin=ss.LOCAL_ORIGIN)
        slept, told = [], []
        backend.sleep = slept.append
        self.assertIs(backend._sleeper(720), backend.sleep, "알릴 곳이 없으면 정한 sleep 그대로")
        backend.progress = told.append
        sleeper = backend._sleeper(720)
        sleeper(10)
        sleeper(20)
        self.assertEqual(slept, [10, 20])
        self.assertEqual(len(told), 2)
        self.assertIn("10초 뒤 다시 확인합니다(1번째 기다림, 최대 720초", told[0])
        self.assertIn("20초 뒤", told[1])
        self.assertIn("check-deploy", told[0])

    def test_the_command_line_connects_the_progress_to_the_error_stream_only(self):
        backend = GitPagesBackend(git=lambda cwd, args, timeout=0, input_bytes=None: None, expected_origin=ss.LOCAL_ORIGIN)
        self.ctx.backend = backend
        out, err = io.StringIO(), io.StringIO()
        cli.main(["list", "--json"], out=out, err=err, ctx=self.ctx)
        self.assertTrue(callable(backend.progress))
        backend.progress("진행 중입니다")
        self.assertEqual(json.loads(out.getvalue())["ok"], True, "표준 출력은 JSON 그대로다")

    def test_the_confirmation_record_has_no_markdown_marks(self):
        project_id = ss.make_approved(self.ctx)
        self.backend.deploy_errors = [AppError("PAGES_DEPLOY_NOT_VISIBLE", detail="### 확인 기록\n- `https://example.invalid/a` → **404** | 두 번째 | > 인용")]
        report = pages_flow.run_pages_publish(self.ctx, project_id, confirmed=True)
        note = next(item for item in report.notes if item.startswith("확인 기록:"))
        for mark in ("#", "`", "*", "|", ">"):
            self.assertNotIn(mark, note)
        self.assertIn("https://example.invalid/a", note)


if __name__ == "__main__":
    unittest.main()
