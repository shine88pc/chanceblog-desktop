"""명령줄 `keys` 시험 — 같은 프로세스 시험(가짜 보관소·가짜 입력)과 진짜 프로세스 시험(시험 전용 가짜 파일 보관소 + 임시 폴더).

지키는 것:
  1) 키는 명령 인자로 받지 않는다(`--stdin` JSON 한 줄이나 터미널의 숨김 입력). 터미널이 아니면 묻지 않고 멈춘다. 입력은 화면에 되풀이되지 않는다.
  2) **어떤 출력에도 키가 없다**: 키 모양 여섯 가지와 긴 무작위 값을 한글·괄호·따옴표·줄바꿈 바로 옆에 두고 이름·프로젝트·키 칸·모르는 칸 이름 자리에 넣어도(거절되든 저장되든) 화면·오류·`--json`·`--verbose` 어디에도 값이 없다.
  3) 읽기 명령(`purposes`·`list`·`usage`·값 없는 `policy`)은 데이터 폴더·보관소를 만들거나 바꾸지 않고, 키가 하나도 없어도 오류 없이 끝난다.
  4) 지우기는 번호 앞 8자와 `--yes` 가 있어야 하고 순번으로는 지우지 않는다. 둘째 키는 약관 확인 표시가 있어야 하고 용도마다 3개까지다.
  5) 영문 상태 코드는 `--json` 에만 있고 사람이 보는 글에는 없다. 종료 코드는 0 정상·1 처리된 오류·2 사용법 오류.
"""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import service_support as ss  # noqa: E402

from chanceblog_desktop.security.keystore import ENV_KEYSTORE, ENV_KEYSTORE_DIR, TEST_DIR_PREFIX, TEST_MARKER, TEST_STORE_VALUE, MemoryStore  # noqa: E402
from chanceblog_desktop.service import cli  # noqa: E402

WORDS = ("needs_check", "not_connected", "auth_error", "rate_limited", "connected", "failover")
HIDDEN_FLAG = 0x08000000                                       # CREATE_NO_WINDOW — 시험이 콘솔 창을 띄우지 않게(Windows 에서만 뜻이 있다)


def key_shapes():
    """가짜 키 모양들 — 저장소에는 키 문자열이 없도록 조각을 이어 붙인다."""
    return {
        "google": "AI" + "za" + "A" * 35,
        "github": "gh" + "p_" + "B" * 36,
        "sk": "s" + "k-" + "C" * 40,
        "aws": "AK" + "IA" + "D" * 16,
        "slack": "xo" + "xb-" + "1" * 12 + "-" + "e" * 12,
        "jwt": "ey" + "J" + "a" * 12 + "." + "b" * 12 + "." + "c" * 12,
        "random": "Q7rT" + "9xLm2" * 8 + "zK",
    }


NEIGHBORS = ("키는{}입니다", "({})", '"{}"', "'{}'", "{}\n다음 줄", "값={}", "\n{}", "한글{}", "{}한글")


def windows(value, size=5):
    return [value[index:index + size] for index in range(len(value) - size + 1)]


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


class CliCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.ctx = ss.make_ctx(self.tmp, clock=ss.Clock())
        self.store = self.ctx.keystore

    def run_keys(self, *argv, stdin="", tty=False, prompt=None, ctx=None):
        out, err = io.StringIO(), io.StringIO()
        source = FakeStdin(stdin, tty)
        code = cli.main(["keys", *argv], out=out, err=err, ctx=ctx or self.ctx, stdin=source, prompt=prompt)
        return code, out.getvalue(), err.getvalue(), source

    def add(self, purpose, name, fields, *extra, **kwargs):
        code, out, err, _source = self.run_keys("add", purpose, "--name", name, "--stdin", *extra, stdin=json.dumps(fields), **kwargs)
        return code, out, err

    def json_out(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        code = cli.main(["--json", "keys", *argv], out=out, err=err, ctx=self.ctx, stdin=FakeStdin(), prompt=None)
        self.assertIn(code, (0, 1), err.getvalue())
        return out.getvalue()


class NoKeyTest(unittest.TestCase):
    def test_every_read_command_works_with_no_key_and_creates_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / "아직 없는 폴더"
            for argv in (("purposes",), ("list",), ("usage",), ("policy", "image_provider"), ("list", "--purpose", "blogger"), ("usage", "--purpose", "github_repo")):
                for json_flag in ((), ("--json",)):
                    with self.subTest(argv=argv, json=json_flag):
                        out, err = io.StringIO(), io.StringIO()
                        code = cli.main([*json_flag, "keys", *argv, "--data-dir", str(data)], out=out, err=err, env={}, stdin=FakeStdin())
                        self.assertEqual((code, err.getvalue()), (0, ""), out.getvalue())
                        self.assertFalse(data.exists(), "읽기 명령은 데이터 폴더를 만들지 않는다")
                        self.assertFalse(out.getvalue().startswith("오류"))
                        self.assertNotIn("코드:", out.getvalue())
                        if not json_flag:
                            self.assertFalse([word for word in WORDS if word in out.getvalue()], "사람이 보는 글에는 영문 상태 코드가 없다")

    def test_read_commands_do_not_even_open_the_keystore_while_there_is_no_entry_and_do_once_there_is_one(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            ctx = ss.make_ctx(tmp, clock=ss.Clock())
            opened = []
            real = ctx.get_keystore

            def counting():
                opened.append(1)
                return real()

            ctx.get_keystore = counting

            def run(*argv, stdin=""):
                out, err = io.StringIO(), io.StringIO()
                return cli.main(list(argv), out=out, err=err, ctx=ctx, stdin=FakeStdin(stdin)), out.getvalue()

            for argv in (("list",), ("usage",), ("list", "--purpose", "image_provider"), ("usage", "--purpose", "naver_openapi")):
                for json_flag in ((), ("--json",)):
                    with self.subTest(argv=argv, json=json_flag):
                        self.assertEqual(run(*json_flag, "keys", *argv)[0], 0)
            self.assertEqual(opened, [], "항목이 하나도 없으면 읽기 명령은 보관소를 열지 않는다")
            self.assertEqual(run("keys", "add", "image_provider", "--name", "기본", "--stdin", stdin=json.dumps({"access_key": "A1b2C3d4E5f6G7h8I9j0K1l2"}))[0], 0)
            opened.clear()
            self.assertEqual(run("keys", "list")[0], 0)
            self.assertTrue(opened, "항목이 있으면 끝 4자를 만들려고 보관소를 연다")

    def test_the_purpose_list_names_the_six_purposes_and_the_image_provider_takes_one_access_key_only(self):
        out, err = io.StringIO(), io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(cli.main(["--json", "keys", "purposes", "--data-dir", str(Path(tmp) / "d")], out=out, err=err, env={}), 0)
        purposes = {item["purpose"]: item for item in json.loads(out.getvalue())["data"]["purposes"]}
        self.assertEqual(list(purposes), ["naver_openapi", "naver_searchad", "image_provider", "ai_assist", "blogger", "github_repo"])
        self.assertEqual([item["name"] for item in purposes["image_provider"]["fields"]], ["access_key"])
        self.assertEqual(purposes["github_repo"]["fields"], [])
        self.assertFalse(purposes["github_repo"]["takes_keys"])
        self.assertTrue(all(item["works_without_key"] for item in purposes.values()))
        self.assertEqual([item["provider"] for item in purposes["image_provider"]["providers"]], ["unsplash", "pexels", "pixabay"])
        self.assertEqual(purposes["image_provider"]["providers"][0]["rotation"], "never")


class AddTest(CliCase):
    FIELDS = {"access_key": "A1b2C3d4E5f6G7h8I9j0K1l2"}

    def test_adding_by_stdin_shows_only_a_masked_tail_and_stores_the_value_in_the_keystore(self):
        code, out, err = self.add("image_provider", "기본", self.FIELDS, "--project", "데스크톱")
        self.assertEqual((code, err), (0, ""), out)
        self.assertIn("끝 4자 ****K1l2", out)
        for window in windows(self.FIELDS["access_key"]):
            self.assertNotIn(window, out)
        self.assertEqual(self.store.get(self.store.list_refs()[0]).reveal("access_key"), self.FIELDS["access_key"])
        self.assertNotIn(self.FIELDS["access_key"], self.ctx.workspace.connections_path.read_text(encoding="utf-8"))
        self.assertFalse([word for word in WORDS if word in out])

    def test_a_short_value_shows_no_tail_at_all(self):
        code, out, err = self.add("naver_openapi", "기본", {"client_id": "abcdefgh12345", "client_secret": "tinysecret1"})
        self.assertEqual((code, err), (0, ""))
        self.assertNotIn("끝 4자", out)
        self.assertNotIn("cret1", out)

    def test_a_key_is_never_taken_as_an_argument(self):
        code, out, err, _ = self.run_keys("add", "image_provider", "--name", "기본", "--access-key", self.FIELDS["access_key"], stdin="")
        self.assertEqual((code, out), (2, ""))
        self.assertNotIn(self.FIELDS["access_key"], err)
        self.assertIn("알 수 없는 항목입니다", err)

    def test_without_a_terminal_and_without_stdin_it_stops_instead_of_asking(self):
        asked = []
        code, out, err, source = self.run_keys("add", "image_provider", "--name", "기본", stdin="", tty=False, prompt=lambda text: asked.append(text) or "x")
        self.assertEqual((code, out, asked), (1, "", []))
        self.assertIn("터미널이 아니어서 키를 물을 수 없습니다", err)
        self.assertEqual(self.store.list_refs(), [])

    def test_on_a_terminal_it_asks_field_by_field_without_echo_and_never_prints_the_answer(self):
        answers = iter(["abcdefgh12345", "tinysecret1"])
        asked = []

        def ask(text):
            asked.append(text)
            return next(answers)

        code, out, err, _ = self.run_keys("add", "naver_openapi", "--name", "기본", tty=True, prompt=ask)
        self.assertEqual((code, err), (0, ""), out)
        self.assertEqual(asked, ["클라이언트 ID(입력은 화면에 보이지 않습니다): ", "클라이언트 시크릿(입력은 화면에 보이지 않습니다): "])
        for value in ("abcdefgh12345", "tinysecret1"):
            self.assertNotIn(value, out + err)
        self.assertEqual(self.store.get(self.store.list_refs()[0]).to_dict(), {"client_id": "abcdefgh12345", "client_secret": "tinysecret1"})

    def test_the_default_hidden_prompt_is_getpass_and_the_answers_never_reach_the_output(self):
        """`prompt` 를 넘기지 않으면 표준 `getpass.getpass`(화면에 되풀이하지 않는 입력)로 묻는다 — `input` 같은 보이는 입력으로 바뀌면 이 시험이 깨진다."""
        from unittest import mock
        answers, asked = iter(["abcdefgh12345", "tinysecret1"]), []

        def fake_getpass(text):
            asked.append(text)
            return next(answers)

        with mock.patch("getpass.getpass", fake_getpass):
            code, out, err, _ = self.run_keys("add", "naver_openapi", "--name", "기본", tty=True)
        self.assertEqual((code, err), (0, ""), out)
        self.assertEqual(len(asked), 2)
        for value in ("abcdefgh12345", "tinysecret1"):
            self.assertNotIn(value, out + err + "".join(asked))

    def test_bad_stdin_is_refused_without_echoing_it(self):
        secret = key_shapes()["google"]
        for text in ("not json " + secret, "[1, 2]", json.dumps({"access_key": 5}), json.dumps({"access_key": secret, "extra": secret}), json.dumps({secret: "x" * 20}), "{" + secret, "",
                     "x" * 9000, json.dumps({"access_key": "짧"})):
            with self.subTest(text=text[:20]):
                code, out, err, _ = self.run_keys("add", "image_provider", "--name", "기본", "--stdin", stdin=text)
                self.assertEqual((code, out), (1, ""))
                self.assertIn("코드: KEY_INVALID_SHAPE", err)
                self.assertNotIn(secret, err)
        self.assertEqual(self.store.list_refs(), [])

    def test_a_stdin_longer_than_the_limit_is_refused_as_too_long_and_one_at_the_limit_is_read(self):
        code, out, err, _ = self.run_keys("add", "image_provider", "--name", "기본", "--stdin", stdin=" " * 8193)
        self.assertEqual((code, out), (1, ""))
        self.assertIn("너무 깁니다(최대 8192자)", err)
        padded = json.dumps({"access_key": "A1b2C3d4E5f6G7h8I9j0K1l2"}) + " " * (8192 - len(json.dumps({"access_key": "A1b2C3d4E5f6G7h8I9j0K1l2"})))
        self.assertEqual(len(padded), 8192)
        code, out, err, _ = self.run_keys("add", "image_provider", "--name", "기본", "--stdin", stdin=padded)
        self.assertEqual((code, err), (0, ""), out)

    def test_the_terms_check_comes_before_the_key_is_read_and_every_later_key_needs_it(self):
        self.add("naver_openapi", "기본", {"client_id": "abcdefgh12345", "client_secret": "tinysecret1"})
        other = {"client_id": "zyxwvuts98765", "client_secret": "othersecret2"}
        code, out, err, source = self.run_keys("add", "naver_openapi", "--name", "예비", "--stdin", stdin=json.dumps(other))
        self.assertEqual((code, out, source.reads), (1, "", 0))
        self.assertIn("코드: KEY_FAILOVER_TERMS_REQUIRED", err)
        self.assertIn("키를 끝없이 돌려 쓰는 기능은 이 프로그램에 없습니다(용도마다 3개까지이고, 다른 앱의 키로 넘어가는 것은 한도·일시 오류일 때뿐입니다)", err)
        code, out, err = self.add("naver_openapi", "예비", other, "--i-understand-terms", "--state", "예비")
        self.assertEqual((code, err), (0, ""))
        self.assertIn("서비스 약관에서 금지될 수 있습니다", out)
        listed = json.loads(self.json_out("list"))["data"]["purposes"][0]["entries"]
        self.assertEqual([item["terms_ack_at"] != "" for item in listed], [False, True])
        self.assertEqual([item["state"] for item in listed], ["active", "standby"], "--state 예비 는 예비로 저장된다")

    def test_at_most_three_entries_per_purpose(self):
        for number, name in enumerate(("가", "나", "다")):
            self.assertEqual(self.add("image_provider", name, {"access_key": f"key{number}" + "Z" * 20}, "--i-understand-terms")[0], 0)
        code, out, err = self.add("image_provider", "라", {"access_key": "key9" + "Z" * 20}, "--i-understand-terms")
        self.assertEqual((code, out), (1, ""))
        self.assertIn("코드: KEY_ENTRY_LIMIT", err)
        self.assertEqual(len(self.store.list_refs()), 3)

    def test_the_git_purpose_takes_no_key(self):
        code, out, err, _ = self.run_keys("add", "github_repo", "--name", "기본", "--stdin", stdin="{}")
        self.assertEqual((code, out), (1, ""))
        self.assertIn("Git 자격 증명 관리자", err)
        self.assertEqual(self.store.list_refs(), [])


class NoLeakTest(CliCase):
    def test_no_output_ever_contains_a_key_shape_next_to_korean_text_brackets_quotes_or_newlines(self):
        """키 모양 7종 × 이웃 9가지 × 자리(이름·프로젝트·키 칸·모르는 칸 이름) × 출력 방식(사람·--json·--verbose) 전수."""
        leaked = []
        for label, shape in key_shapes().items():
            for neighbor in NEIGHBORS:
                text = neighbor.format(shape)
                trials = {"name": ("add", "image_provider", "--name", text, "--stdin"), "project": ("add", "image_provider", "--name", "기본", "--project", text, "--stdin")}
                bodies = {"name": {"access_key": "Zz9Yy8Xx7Ww6Vv5Uu4Tt3Ss2"}, "project": {"access_key": "Zz9Yy8Xx7Ww6Vv5Uu4Tt3Ss2"}}
                for slot, argv in trials.items():
                    for mode in ((), ("--json",), ("--verbose",)):
                        self.setUp()
                        out, err = io.StringIO(), io.StringIO()
                        code = cli.main([*mode, "keys", *argv], out=out, err=err, ctx=self.ctx, stdin=FakeStdin(json.dumps(bodies[slot])), prompt=None)
                        text_out = out.getvalue() + err.getvalue()
                        if shape in text_out or any(window in text_out for window in windows(shape, 8)):
                            leaked.append((label, neighbor, slot, mode, code))
                for slot, body in (("value", {"access_key": text}), ("unknown-name", {text: "Zz9Yy8Xx7Ww6Vv5Uu4Tt3Ss2"}), ("extra", {"access_key": "Zz9Yy8Xx7Ww6Vv5Uu4Tt3Ss2", "x": text})):
                    for mode in ((), ("--json",), ("--verbose",)):
                        self.setUp()
                        out, err = io.StringIO(), io.StringIO()
                        code = cli.main([*mode, "keys", "add", "image_provider", "--name", "기본", "--stdin"], out=out, err=err, ctx=self.ctx, stdin=FakeStdin(json.dumps(body)), prompt=None)
                        text_out = out.getvalue() + err.getvalue()
                        if any(window in text_out for window in windows(shape, 8)) or (label != "random" and shape in text_out):
                            leaked.append((label, neighbor, slot, mode, code))
        self.assertEqual(leaked, [])

    def test_a_key_typed_into_the_wrong_place_is_not_echoed_by_the_usage_errors_either(self):
        """키를 인자 자리에 잘못 친 경우(모르는 옵션·잘못된 용도·잘못된 값·`=` 로 붙인 값) argparse 가 되풀이하는 사용법 오류에도 값이 없다."""
        leaked = []
        for label, shape in key_shapes().items():
            for argv in (("add", "image_provider", "--name", "기본", "--access-key", shape), ("add", "image_provider", "--name", "기본", f"--access-key={shape}"), ("add", shape, "--name", "기본"),
                         ("policy", "naver_openapi", "--on-limit", shape), ("state", "1", shape), ("usage", "--purpose", shape), ("list", shape), ("remove", "1", shape, "--yes"),
                         ("add", "image_provider", "--name", "기본", "--stdin", shape), ("order",), ("add", "image_provider", shape)):
                for mode in ((), ("--json",), ("--verbose",)):
                    out, err = io.StringIO(), io.StringIO()
                    code = cli.main([*mode, "keys", *argv], out=out, err=err, ctx=self.ctx, stdin=FakeStdin(), prompt=None)
                    text = out.getvalue() + err.getvalue()
                    if any(window in text for window in windows(shape, 8)):
                        leaked.append((label, argv, mode, code))
        self.assertEqual(leaked, [])
        self.assertEqual(self.store.list_refs(), [])

    def test_usage_errors_of_every_command_repeat_nothing_that_was_typed_even_with_dashes_newlines_and_backslashes(self):
        """`keys` 가 아닌 명령·대시로 시작하는 값·줄바꿈·탭·역슬래시가 든 값도 사용법 오류에 되풀이되지 않는다(argparse 의 문구 대신 값 없는 고정 문장)."""
        pieces = ("Qm7Xc2Vb9Nk4", "9Nk4Lp8Rt3", "Wz6Yh1", "Jd5Sf0Ga")
        leaked = []
        mixed = "Qm7Xc2Vb" + chr(10) + "9Nk4Lp8Rt3" + chr(92) + "Wz6Yh1" + chr(9) + "Jd5Sf0Ga"                  # 줄바꿈·역슬래시·탭이 든 값
        for secret in ("Qm7Xc2Vb9Nk4Lp8Rt3Wz6Yh1Jd5Sf0Ga", "-Qm7Xc2Vb9Nk4Lp8Rt3Wz6Yh1Jd5Sf0Ga", mixed):
            for argv in (["doctor", secret], ["candidates", "list", secret], ["list", secret], ["naver-profile", "show", secret], ["publish-pages", "1", "--wait", secret],
                         ["candidates", "add", "--topic", "a", "--keyword", "b", "--blog", secret], ["candidates", "list", "--status", secret], ["review", "1", "--platform", secret],
                         ["keys", "list", secret], ["keys", "add", secret], ["--bogus", secret], [secret],
                         ["draft", "plan", "1", "--bogus", secret], ["draft", "plan", "1", "--blog", secret], ["draft", "plan", "1", "--type", secret], ["draft", secret],
                         ["draft", "plan", "1", "--length", secret], ["draft", "plan", "1", "--url", secret], ["draft", "plan", "1", "--experience"], ["draft", "plan"],
                         ["doctor", f"--json={secret}"], ["candidates", "list", f"--json={secret}"], ["keys", "list", f"--json={secret}"], ["keys", "remove", "1", f"--yes={secret}"],
                         ["keys", "list", f"-h{secret}"], ["draft", "plan", "1", f"--json={secret}"]):          # `--옵션=값`·`-h값` 꼴(argparse 의 '값을 붙일 수 없다' 문구) — 독립 검증 2차 중간 지적
                out, err = io.StringIO(), io.StringIO()
                code = cli.main(argv, out=out, err=err, ctx=self.ctx, stdin=FakeStdin())
                text = out.getvalue() + err.getvalue()
                if any(piece in text for piece in pieces):
                    leaked.append((argv[:3], code))
        self.assertEqual(leaked, [])

    def test_the_last_gate_masks_a_key_shape_that_slips_into_an_error_detail_or_a_value(self):
        """마지막 관문(`security.mask`) — 오류 세부·`--json` 값·`--verbose` 기록 줄에 키 모양이 새어 들어가도 출력에는 가려져 나간다(`keys list` 가 일부러 그런 오류를 내게 바꿔 확인)."""
        from unittest import mock

        from chanceblog_desktop.errors import AppError
        shape = key_shapes()["google"]
        for mode in ((), ("--json",), ("--verbose",), ("--json", "--verbose")):
            with self.subTest(mode=mode):
                problem = AppError("UNEXPECTED_ERROR", detail=f"세부에 {shape} 이(가) 섞임")
                with mock.patch.object(cli, "cmd_keys_list", side_effect=problem):
                    out, err = io.StringIO(), io.StringIO()
                    code = cli.main([*mode, "keys", "list"], out=out, err=err, ctx=self.ctx, stdin=FakeStdin())
                self.assertEqual(code, 1)
                self.assertNotIn(shape, out.getvalue() + err.getvalue())
                self.assertIn("[가림", out.getvalue() + err.getvalue())

    def test_the_last_gate_masks_a_key_shape_inside_the_slots_of_an_error_message_which_the_detail_masking_does_not_reach(self):
        """오류 문구의 칸(「…」 자리)에 키 모양이 들어가도 화면에는 가려져 나간다 — 세부 가리기와 별개로 마지막 관문이 한 번 더 막는다."""
        from unittest import mock

        from chanceblog_desktop.errors import AppError
        masked_shapes = {name: value for name, value in key_shapes().items() if name != "random"}               # 마스크가 아는 모양(긴 무작위 값은 `keys` 의 자기 검사가 맡는다)
        for name, shape in masked_shapes.items():
            for pattern in ("{}", "({})", '"{}"', "키는 {} 입니다"):
                for mode in ((), ("--verbose",), ("--json",)):
                    with self.subTest(shape=name, pattern=pattern, mode=mode):
                        problem = AppError("CANDIDATE_NOT_FOUND", {"항목": pattern.format(shape)})
                        with mock.patch.object(cli, "cmd_keys_list", side_effect=problem):
                            out, err = io.StringIO(), io.StringIO()
                            code = cli.main([*mode, "keys", "list"], out=out, err=err, ctx=self.ctx, stdin=FakeStdin())
                        self.assertEqual(code, 1)
                        text = out.getvalue() + err.getvalue()
                        self.assertNotIn(shape, text)
                        self.assertIn("[가림", text)

    def test_the_last_gate_also_masks_a_key_shape_inside_a_successful_result_in_text_and_in_json(self):
        """성공한 결과의 글줄과 `--json` 데이터에 키 모양이 섞여 들어가도 출력에는 가려져 나간다(`keys list` 가 일부러 그런 결과를 내게 바꿔 확인)."""
        from unittest import mock
        shape = key_shapes()["github"]
        for mode in ((), ("--json",)):
            with self.subTest(mode=mode):
                result = cli.Output([f"한 줄 {shape} 끝", f"키는{shape}입니다"], {"값": [shape, {"안쪽": f"({shape})"}]})
                with mock.patch.object(cli, "cmd_keys_list", return_value=result):
                    out, err = io.StringIO(), io.StringIO()
                    code = cli.main([*mode, "keys", "list"], out=out, err=err, ctx=self.ctx, stdin=FakeStdin())
                self.assertEqual((code, err.getvalue()), (0, ""))
                self.assertNotIn(shape, out.getvalue())
                self.assertGreaterEqual(out.getvalue().count("[가림"), 2)

    def test_a_usage_error_raised_after_parsing_is_cleaned_of_typed_values_too(self):
        """처리기가 낸 사용법 오류(파싱은 통과한 뒤)의 문구에 사용자가 친 값이 섞여 있어도 되풀이되지 않는다."""
        from unittest import mock
        typed = "내가친값ZXQ"
        with mock.patch.object(cli, "cmd_keys_add", side_effect=cli.UsageError(f"이상한 값 {typed} 입니다")):
            out, err = io.StringIO(), io.StringIO()
            code = cli.main(["keys", "add", "image_provider", "--name", typed], out=out, err=err, ctx=self.ctx, stdin=FakeStdin())
        self.assertEqual(code, 2)
        self.assertNotIn(typed, out.getvalue() + err.getvalue())
        self.assertIn("이상한 값 (입력값) 입니다", err.getvalue())

    def test_the_explicit_argument_message_of_argparse_is_translated_without_the_value_and_in_linear_time(self):
        """`--json=<값>`·`-h<값>` 은 argparse 가 '값을 붙일 수 없다' 문구에 값을 따옴표로 되풀이한다 — 번역 규칙이 값 없는 고정 문장으로 바꾸고(독립 검증 2차), 규칙은 문구 맨 앞에서만 맞아 긴 값에서도 느려지지 않는다."""
        import time
        for typed in ("Qm7Xc2Vb9Nk4Lp8Rt3Wz6Yh1Jd5Sf0Ga", "줄\n바꿈\\역슬래시\t탭", "x"):
            with self.assertRaises(cli.UsageError) as caught:
                cli.KoreanParser(prog="p").error(f"argument --json: ignored explicit argument {typed!r}")
            self.assertEqual(str(caught.exception), "--json 에는 값을 붙일 수 없습니다(입력한 값은 보이지 않습니다)")
        with self.assertRaises(cli.UsageError) as caught:
            cli.KoreanParser(prog="p").error("argument -h/--help: ignored explicit argument 'Zk9'")
        self.assertNotIn("Zk9", str(caught.exception))
        started = time.perf_counter()
        for message in ("argument --json: ignored explicit argument '" + "a: " * 30000 + "'",
                        "argument --wait: " + "argument a: " * 9000,                                  # 'argument ' 가 수천 번 나오는 긴 문구 — 규칙이 문구 맨 앞에 고정되지 않으면 시작 위치마다 훑어 제곱 시간
                        "argument --wait: invalid choice: '" + "argument a: " * 9000 + "' (choose from 1, 2)"):
            with self.assertRaises(cli.UsageError):
                cli.KoreanParser(prog="p").error(message)
        self.assertLess(time.perf_counter() - started, 3.0, "긴 값에서 번역 규칙이 느려지면 안 된다(제곱 시간이던 것을 문구 맨 앞 고정으로 고쳤다)")

    def test_saved_keys_never_appear_in_any_command_output_or_file(self):
        values = {}
        for number, (label, shape) in enumerate(key_shapes().items()):
            purpose = ("naver_openapi", "naver_searchad", "image_provider", "ai_assist", "blogger")[number % 5]
            spec_fields = {"naver_openapi": {"client_id": "id" + shape[:14], "client_secret": shape[:30]}, "naver_searchad": {"customer_id": "1234567", "access_license": shape, "secret_key": shape[::-1]},
                           "image_provider": {"access_key": shape}, "ai_assist": {"key": shape}, "blogger": {"client_id": "cid" + shape[:20], "client_secret": shape[:24], "refresh_token": shape}}[purpose]
            if number >= 5:
                continue
            code, out, err = self.add(purpose, f"항목{number}", spec_fields)
            self.assertEqual(code, 0, (label, err))
            values[label] = list(spec_fields.values())
        every = [value for items in values.values() for value in items if len(value) >= 8]
        commands = (("list",), ("usage",), ("purposes",), ("policy", "image_provider"), ("test", "1"), ("state", "1", "예비"), ("state", "1", "사용"), ("order", "naver_openapi", "1"), ("remove", "1"), ("remove", "zzzzzz"))
        texts = []
        for argv in commands:
            for mode in ((), ("--json",), ("--verbose",)):
                out, err = io.StringIO(), io.StringIO()
                cli.main([*mode, "keys", *argv], out=out, err=err, ctx=self.ctx, stdin=FakeStdin(), prompt=None)
                texts.append(out.getvalue() + err.getvalue())
        for path in self.ctx.workspace.root.rglob("*"):
            if path.is_file():
                texts.append(path.read_text(encoding="utf-8", errors="replace"))
        for text in texts:
            for value in every:
                self.assertNotIn(value, text)
                for window in windows(value, 8):
                    self.assertNotIn(window, text)

    def test_the_backup_and_the_diagnostic_paths_never_carry_a_key(self):
        value = key_shapes()["google"]
        self.assertEqual(self.add("image_provider", "기본", {"access_key": value})[0], 0)
        code, out, err = ss.run_cli(self.ctx, "backup")
        self.assertEqual(code, 0, err)
        code, doctor_out, doctor_err = ss.run_cli(self.ctx, "--json", "doctor")
        everything = out + err + doctor_out + doctor_err + "".join(path.read_text(encoding="utf-8", errors="replace") if path.suffix in (".json", ".bak", ".lock") else path.read_bytes().decode("latin-1")
                                                                       for path in self.ctx.workspace.root.rglob("*") if path.is_file())
        self.assertNotIn(value, everything)
        self.assertNotIn(value[-4:] * 2, everything)
        from chanceblog_desktop.service import connections as cn
        summary = json.dumps(cn.diagnostic_summary(self.ctx), ensure_ascii=False)
        self.assertNotIn(value[-4:], summary)
        self.assertNotIn("기본", summary)


class ManageTest(CliCase):
    def setUp(self):
        super().setUp()
        for number, name in enumerate(("가", "나")):
            extra = ("--i-understand-terms",) if number else ()
            self.assertEqual(self.add("naver_openapi", name, {"client_id": f"app{number}" + "x" * 12, "client_secret": f"sec{number}abcdefg"}, "--project", f"앱{number}", *extra)[0], 0)
        self.ids = [item["entry_id"] for item in json.loads(self.json_out("list"))["data"]["purposes"][0]["entries"]]

    def test_removing_needs_the_confirmation_and_a_number_not_an_ordinal(self):
        before = ss.tree_snapshot(self.ctx.workspace.root)
        refs = list(self.store.list_refs())
        code, out, err, _ = self.run_keys("remove", self.ids[0][:8])
        self.assertEqual((code, out), (1, ""))
        self.assertIn("코드: CONFIRMATION_REQUIRED", err)
        self.assertIn(f"keys remove {self.ids[0][:8]} --yes", err)
        for ref in ("1", self.ids[0][:5], self.ids[0][:7]):
            code, out, err, _ = self.run_keys("remove", ref, "--yes")
            self.assertEqual((code, out), (1, ""), ref)
            self.assertIn("코드: CONNECTION_DELETE_NEEDS_NUMBER", err)
        self.assertEqual((ss.tree_snapshot(self.ctx.workspace.root), self.store.list_refs()), (before, refs))
        code, out, err, _ = self.run_keys("remove", self.ids[0][:8], "--yes", "--keep-cache")
        self.assertEqual((code, err), (0, ""))
        self.assertIn("캐시", out)
        self.assertEqual(len(self.store.list_refs()), 1)

    def test_remove_by_the_full_number_and_a_second_remove_reports_not_found(self):
        self.assertEqual(self.run_keys("remove", self.ids[1], "--yes")[0], 0)
        code, out, err, _ = self.run_keys("remove", self.ids[1][:8], "--yes")
        self.assertEqual(code, 1)
        self.assertIn("코드: CONNECTION_NOT_FOUND", err)

    def test_state_order_policy_and_test(self):
        code, out, err, _ = self.run_keys("state", "2", "꺼짐")
        self.assertEqual((code, err), (0, ""))
        self.assertIn("사용 → 꺼짐", out)
        self.assertEqual(self.run_keys("state", "2", "off")[0], 0)
        self.assertEqual(self.run_keys("state", "2", "멈춤")[0], 2)
        code, out, err, _ = self.run_keys("order", "naver_openapi", self.ids[1][:8])
        self.assertEqual((code, err), (0, ""))
        self.assertLess(out.index("나"), out.index("가"))
        self.assertEqual(self.run_keys("order", "naver_openapi", self.ids[1][:8], self.ids[1][:8])[0], 1)
        self.assertEqual(self.run_keys("order", "image_provider", self.ids[0][:8])[0], 1)
        code, out, err, _ = self.run_keys("policy", "naver_openapi")
        self.assertIn("허용된 다음 키로 전환", out)
        for value, words in (("save", "절약 모드만"), ("failover", "허용된 다음 키로 전환")):
            code, out, err, _ = self.run_keys("policy", "naver_openapi", "--on-limit", value)
            self.assertEqual((code, err), (0, ""), value)
            self.assertIn("정책을 바꿨습니다", out)
            self.assertIn(words, out)
        self.assertEqual(self.run_keys("policy", "naver_openapi", "--on-limit", "maybe")[0], 2)
        self.assertEqual(self.run_keys("policy", "naver_openapi", "--tier", "production")[0], 1)
        code, out, err, _ = self.run_keys("test", "1")
        self.assertEqual((code, err), (0, ""))
        self.assertIn("시험 기능 준비 중", out)

    def test_read_commands_change_nothing_even_when_entries_exist(self):
        before = ss.tree_snapshot(self.ctx.workspace.root)
        blobs = dict(self.store._blobs)
        for argv in (("list",), ("usage",), ("purposes",), ("policy", "naver_openapi"), ("test", "1"), ("list", "--purpose", "naver_openapi"), ("usage", "--purpose", "image_provider")):
            with self.subTest(argv=argv):
                self.assertEqual(self.run_keys(*argv)[0], 0)
        self.assertEqual(ss.tree_snapshot(self.ctx.workspace.root), before)
        self.assertEqual(dict(self.store._blobs), blobs)

    def test_the_list_shows_names_states_and_badges_in_korean_and_the_number_prefix(self):
        code, out, err, _ = self.run_keys("list")
        self.assertEqual((code, err), (0, ""))
        for needle in ("[1] 가 — 사용 · 연결 확인 필요", "[2] 나 — 사용 · 연결 확인 필요", f"번호 {self.ids[0][:8]}", "소속 앱0", "마지막 확인 없음", "네이버 오픈 API(검색·데이터랩): 연결 확인 필요"):
            self.assertIn(needle, out)
        self.assertFalse([word for word in WORDS if word in out])
        self.assertNotIn(self.ids[0], out)
        verbose = self.run_keys("--verbose", "list")[1]
        self.assertEqual(verbose, out, "--verbose 는 목록 모양을 바꾸지 않는다")
        self.assertIn(self.ids[0], self.json_out("list"))


class ProcessTest(unittest.TestCase):
    """진짜 `python -m chanceblog_desktop` — 시험 전용 가짜 파일 보관소(임시 폴더 + 표시 파일 + 환경 변수 `CHANCEBLOG_KEYSTORE=memory-file`)로만 키를 넣는다."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.data = self.tmp / "데이터"
        self.keys = Path(tempfile.mkdtemp(prefix=TEST_DIR_PREFIX))
        (self.keys / TEST_MARKER).write_text("", encoding="utf-8")
        self.addCleanup(shutil.rmtree, self.keys, ignore_errors=True)
        self.env = {**ss.env_without_repo(), "PYTHONPATH": str(ss.ROOT / "src"), "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1", ENV_KEYSTORE: TEST_STORE_VALUE, ENV_KEYSTORE_DIR: str(self.keys)}

    def command(self, *argv):
        return [sys.executable, "-X", "utf8", "-m", "chanceblog_desktop", "--data-dir", str(self.data), "keys", *argv]

    def launch(self, *argv, stdin=None):
        flags = {"creationflags": HIDDEN_FLAG} if os.name == "nt" else {}
        return subprocess.Popen(self.command(*argv), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=self.env, cwd=self.tmp, **flags)

    def run_module(self, *argv, stdin=""):
        process = self.launch(*argv)
        out, err = process.communicate(stdin.encode("utf-8"), timeout=180)
        text_out, text_err = out.decode("utf-8"), err.decode("utf-8")
        self.assertNotIn("Traceback", text_err)
        return process.returncode, text_out, text_err

    def test_a_real_session_with_real_exit_codes(self):
        code, out, err = self.run_module("list")
        self.assertEqual((code, err), (0, ""))
        self.assertIn("키 항목이 아직 없습니다", out)
        self.assertFalse(self.data.exists(), "읽기 명령은 데이터 폴더를 만들지 않는다")
        self.assertEqual(list(self.keys.glob("fake-keystore*")), [], "읽기 명령은 보관소 파일을 만들지 않는다")
        value = key_shapes()["google"]
        code, out, err = self.run_module("add", "image_provider", "--name", "기본", "--stdin", stdin=json.dumps({"access_key": value}))
        self.assertEqual(code, 0, err)
        self.assertIn("시험 전용 가짜 보관소를 쓰는 중입니다", out)
        self.assertNotIn(value, out + err)
        code, out, err = self.run_module("list")
        self.assertEqual(code, 0)
        self.assertIn("끝 4자 ****AAAA", out)
        self.assertNotIn(value, out)
        code, out, err = self.run_module("--json", "usage")
        self.assertEqual(code, 0)
        self.assertNotIn(value, out)
        code, out, err = self.run_module("add", "image_provider", "--name", "둘", "--stdin", stdin=json.dumps({"access_key": "Zz9Yy8Xx7Ww6Vv5Uu4Tt3Ss2"}))
        self.assertEqual(code, 1)
        self.assertIn("KEY_FAILOVER_TERMS_REQUIRED", err)
        self.assertEqual(self.run_module("remove", "1", "--yes")[0], 1)
        number = json.loads(self.run_module("--json", "list")[1])["data"]["purposes"][2]["entries"][0]["entry_id"][:8]
        self.assertEqual(self.run_module("remove", number, "--yes")[0], 0)
        self.assertEqual(self.run_module("add", "image_provider", "--name", "기본", "--stdin", stdin="x")[0], 1)

    def test_two_processes_adding_at_the_same_time_both_succeed_without_losing_one(self):
        first = self.launch("add", "naver_openapi", "--name", "가", "--stdin")
        second = self.launch("add", "naver_searchad", "--name", "나", "--stdin")
        bodies = ({"client_id": "abcdefgh12345", "client_secret": "tinysecret1"}, {"customer_id": "1234567", "access_license": "L" * 20, "secret_key": "K" * 20})
        results = [process.communicate(json.dumps(body).encode("utf-8"), timeout=180) for process, body in zip((first, second), bodies, strict=True)]
        self.assertEqual([process.returncode for process in (first, second)], [0, 0], results)
        listed = json.loads(self.run_module("--json", "list")[1])["data"]["purposes"]
        self.assertEqual([len(group["entries"]) for group in listed], [1, 1, 0, 0, 0])

    def test_the_test_only_keystore_refuses_a_folder_without_the_marker_and_says_so_in_plain_korean(self):
        (self.keys / TEST_MARKER).unlink()
        code, out, err = self.run_module("add", "image_provider", "--name", "기본", "--stdin", stdin=json.dumps({"access_key": "A1b2C3d4E5f6G7h8I9j0K1l2"}))
        self.assertEqual((code, out), (1, ""))
        self.assertIn("코드: KEY_STORE_UNAVAILABLE", err)
        self.assertFalse(self.data.exists() and (self.data / "connections.json").exists())
        (self.keys / TEST_MARKER).write_text("", encoding="utf-8")

    def test_usage_errors_of_a_real_process_never_repeat_what_was_typed(self):
        """진짜 프로세스(`argv` 를 넘기지 않는 실행)에서 키를 인자 자리에 잘못 쳤을 때의 사용법 오류에도 값이 없다 — 시험이 `argv` 를 직접 넘기면 이 구멍이 안 보였다."""
        secret = "Qm7Xc2Vb9Nk4Lp8Rt3Wz6Yh1Jd5Sf0Ga"
        for argv in (("list", "--purpose", secret), ("list", "--bogus-flag", secret), ("add", secret, "--name", "기본"), ("policy", "naver_openapi", "--on-limit", secret), ("state", "1", secret),
                     ("usage", "--purpose", secret), ("list", secret), ("remove", "1", secret, "--yes"), ("add", "image_provider", "--name", "기본", f"--access-key={secret}"), ("order",)):
            with self.subTest(argv=argv[:3]):
                code, out, err = self.run_module(*argv)
                self.assertIn(code, (1, 2))
                self.assertNotIn(secret, out + err)

    def run_other(self, *argv):
        """`keys` 가 아닌 명령을 진짜 프로세스로(같은 환경·창 없음)."""
        flags = {"creationflags": HIDDEN_FLAG} if os.name == "nt" else {}
        process = subprocess.run([sys.executable, "-X", "utf8", "-m", "chanceblog_desktop", "--data-dir", str(self.data), *argv], input=b"", capture_output=True, env=self.env, cwd=self.tmp, timeout=180, **flags)
        text_out, text_err = process.stdout.decode("utf-8"), process.stderr.decode("utf-8")
        self.assertNotIn("Traceback", text_err)
        return process.returncode, text_out, text_err

    def test_a_value_glued_to_an_option_with_an_equals_sign_is_not_repeated_by_a_real_process_either(self):
        """`--옵션=값`·`-h값` 꼴로 키를 잘못 붙여 쳐도 진짜 프로세스의 사용법 오류에 값이 없다 — `keys` 가 아닌 명령도 같다(독립 검증 2차의 중간 지적: 전에는 `doctor --json=<값>` 이 값을 되풀이했고 줄바꿈·역슬래시가 든 값은 `keys` 에서도 샜다)."""
        pieces = ("Qm7Xc2Vb", "9Nk4Lp8Rt3", "Wz6Yh1", "Jd5Sf0Ga")
        for value in ("Qm7Xc2Vb9Nk4Lp8Rt3Wz6Yh1Jd5Sf0Ga", "Qm7Xc2Vb" + chr(10) + "9Nk4Lp8Rt3" + chr(92) + "Wz6Yh1" + chr(9) + "Jd5Sf0Ga"):
            for argv in (("keys", "list", f"--json={value}"), ("keys", "remove", "1", f"--yes={value}"), ("keys", "add", "image_provider", "--name", "기본", f"--stdin={value}"),
                         ("keys", "list", f"-h{value}"), ("doctor", f"--json={value}"), ("candidates", "list", f"--json={value}"), ("draft", "plan", "1", f"--json={value}")):
                with self.subTest(argv=argv[:3], value=value[:3] + str(len(value))):
                    code, out, err = self.run_other(*argv)
                    self.assertIn(code, (0, 2) if argv[-1].startswith("-h") else (2,), (out, err))         # `-h<값>` 은 파이썬 버전에 따라 도움말(0)이나 사용법 오류(2) — 어느 쪽이든 값은 없다
                    self.assertEqual([piece for piece in pieces if piece in out + err], [], argv)

    def test_help_is_korean(self):
        code, out, err = self.run_module("--help")
        self.assertEqual((code, err), (0, ""))
        for needle in ("사용법:", "purposes", "add", "remove", "usage", "policy"):
            self.assertIn(needle, out)
        for word in ("usage:", "positional arguments", "options:"):
            self.assertNotIn(word, out.replace("keys usage", "").replace(" usage ", " "))


class DefaultStoreSafetyTest(unittest.TestCase):
    def test_a_context_without_an_injected_store_never_opens_a_fake_one_unless_the_guarded_variable_is_set(self):
        ctx = ss.make_ctx(tempfile.mkdtemp())
        ctx.keystore = None
        ctx.env = {}
        if os.name != "nt":
            from chanceblog_desktop.errors import AppError
            with self.assertRaises(AppError) as caught:
                ctx.get_keystore()
            self.assertEqual(caught.exception.code, "KEY_STORE_UNAVAILABLE")
        ctx.env = {ENV_KEYSTORE: TEST_STORE_VALUE}
        from chanceblog_desktop.errors import AppError
        with self.assertRaises(AppError):
            ctx.get_keystore()

    def test_the_default_test_context_uses_the_in_memory_store(self):
        self.assertIsInstance(ss.make_ctx(tempfile.mkdtemp()).keystore, MemoryStore)


if __name__ == "__main__":
    unittest.main()
