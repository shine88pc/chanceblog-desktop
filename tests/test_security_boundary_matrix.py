"""위치 × 이름 표 시험 — 운영자가 정한 '비밀이 나가면 안 되는 11곳' 마다 '대상 이름 11개'의 카나리(가짜 비밀)를 실제로 흘려 보내 **새는 것 0** 을 확인한다(PCSEC1 H1).

위치(11): 일반 로그 · 오류 로그 · 예외 문구 · 스택 추적 · 진단 정보(doctor) · 연결 시험 결과 · URL 질의 · 요청 헤더 · UI 메시지 · 시험 실패 출력 · 워크플로 산출물.
이름(11): Authorization · api_key · apikey · serviceKey · access_token · refresh_token · client_secret · password · Cookie · Set-Cookie · X-API-Key.
칸마다: 그 이름이 그 위치에서 나타나는 자연스러운 모양(헤더 줄·`이름=값`·주소 질의)의 글에 이름마다 다른 카나리를 넣어 그 위치의 실제 경로(로깅·오류 렌더링·`cli.main` 의 세 출력 모드·`sys.excepthook`·doctor 점검·연결 시험 문장·화면 뷰모델 …)로 흘리고,
출력에 카나리의 원문·퍼센트·16진수·base64·조각이 하나라도 있으면 샌 것이다. 실패 메시지는 (위치, 이름, 경로 이름)뿐이다 — 값을 적지 않는다. 해당 없는 칸(헤더 전용 이름이 주소 질의로 오는 일 — `Authorization`·`Cookie`·`Set-Cookie`)은 표에 'n/a' 로 남긴다.
Qt 위젯 글 훑기(UI 메시지의 화면 쪽)는 `test_security_boundary_qt.py`, 워크플로 산출물 규칙의 실제 검사는 `test_workflow_artifacts.py` 가 한다(이 표의 11번째 칸은 그 규칙이 이름마다 어기는 합성 워크플로를 잡는지).
네트워크·실제 보관소 없이 돈다. 가짜 비밀은 `CANARY_` 로 시작하는 문자열을 런타임에 만든다.
"""
import contextlib
import io
import logging
import os
import re
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
import secret_support as sec  # noqa: E402
import service_support as ss  # noqa: E402
import test_workflow_artifacts as wf  # noqa: E402

from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.publish.gitrepo import GitResult  # noqa: E402
from chanceblog_desktop.security import boundary  # noqa: E402
from chanceblog_desktop.security.keystore import MemoryStore  # noqa: E402
from chanceblog_desktop.security.mask import mask, safe_detail  # noqa: E402
from chanceblog_desktop.service import cli  # noqa: E402
from chanceblog_desktop.service import connections as cn  # noqa: E402
from chanceblog_desktop.service import doctor  # noqa: E402
from chanceblog_desktop.service import format as fmt  # noqa: E402
from chanceblog_desktop.ui.core import app_state  # noqa: E402
from chanceblog_desktop.ui.core.jobs import JobFailure  # noqa: E402
from chanceblog_desktop.ui.core.notify import ToastPolicy  # noqa: E402
from chanceblog_desktop.ui.core.text import display_text  # noqa: E402

NAMES = ("Authorization", "api_key", "apikey", "serviceKey", "access_token", "refresh_token", "client_secret", "password", "Cookie", "Set-Cookie", "X-API-Key")
LOCATIONS = ("일반 로그", "오류 로그", "예외 문구", "스택 추적", "진단 정보(doctor)", "연결 시험 결과", "URL 질의", "요청 헤더", "UI 메시지", "시험 실패 출력", "워크플로 산출물")
NOT_APPLICABLE = {("URL 질의", "Authorization"), ("URL 질의", "Cookie"), ("URL 질의", "Set-Cookie")}          # 헤더 전용 이름은 주소 질의로 오지 않는다
OUTPUT_MODES = ([], ["--verbose"], ["--json"], ["--json", "--verbose"])


def canary_of(name):
    return sec.make_canary(re.sub(r"[^A-Za-z0-9]+", "_", name).upper())


def carrier(name, canary, form):
    """이름이 `form`(`assign`·`header`·`query`) 자리에서 나타나는 모양의 글(카나리가 값이다). 헤더 전용 이름은 어느 자리에서나 헤더 줄 모양이다."""
    if name == "Authorization":
        return f"Authorization: Token {canary}"
    if name == "Cookie":
        return f"Cookie: sid={canary}; theme=dark"
    if name == "Set-Cookie":
        return f"Set-Cookie: auth={canary}; Path=/; HttpOnly"
    if form == "query":
        return f"https://api.example.test/v1/items?page=1&{name}={canary}&sort=asc"
    if form == "header" or name == "X-API-Key":
        return f"{name}: {canary}"
    return f"{name}={canary}"


class Boom(MemoryStore):
    """보관소를 읽다 예상 못 한 예외를 내는 가짜 — 문구는 `message` 칸이 정한다."""
    message = ""

    def exists(self, ref):
        raise RuntimeError(self.message)

    def get(self, ref):
        raise RuntimeError(self.message)


class Matrix(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        assert boundary.active() is None, "다른 시험이 경계를 깔아 둔 채 끝났다"
        cls._tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls._tmp.cleanup)
        cls.ctx = ss.make_ctx(cls._tmp.name)
        cn.add_entry(cls.ctx, "ai_assist", name="기본", fields={"key": sec.make_canary("ENTRY_KEY")}, provider="gemini", keystore=MemoryStore())
        cls.boom = Boom()
        cls.ctx.keystore = cls.boom

    def tearDown(self):
        installed = boundary.active()
        if installed is not None:
            installed.uninstall()

    # ---- 위치마다 '그 위치의 실제 경로로 글을 흘려 나온 출력들' ----
    def run_cli(self, argv, *, patches=()):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.ExitStack() as stack:
            for patch in patches:
                stack.enter_context(patch)
            cli.main(list(argv), out=out, err=err, ctx=self.ctx, env={})
        return out.getvalue() + "\n" + err.getvalue()

    def loc_general_log(self, name, text):
        stream = io.StringIO()
        logger = logging.getLogger("pcsec1.matrix.general")
        handler = logging.StreamHandler(stream)
        logger.addHandler(handler)
        logger.propagate = False
        logger.setLevel(logging.DEBUG)
        err = io.StringIO()
        try:
            with contextlib.redirect_stderr(err), boundary.install():
                logger.warning("요청 실패: %s", text)
                logger.error(f"요청 실패(f-string): {text}")
                try:
                    raise RuntimeError("로그 속 예외 " + text)
                except RuntimeError:
                    logger.exception("실패")
                if not logging.getLogger().handlers:                                    # 처리기가 없는 로거는 마지막 수단(lastResort) 으로 표준 오류에 나간다
                    logging.getLogger("pcsec1.matrix.last").warning("마지막 수단 %s", text)
        finally:
            logger.removeHandler(handler)
        return {"로거 처리기": stream.getvalue(), "표준 오류(lastResort)": err.getvalue()}

    def loc_error_log(self, name, text):
        error = AppError("FILE_WRITE_FAILED", {"경로": text}, detail=text)
        return {"log_line": error.log_line(), "str": str(error), "rendered": error.rendered().message + error.rendered().action, "error_lines": "\n".join(fmt.error_lines(error, verbose=True)),
                "payload": repr(cli._mask_deep(cli._error_payload(error)))}

    def loc_exception_text(self, name, text):
        self.boom.message = "저장소 연결 실패 " + text
        return {" ".join(flags) or "(기본)": self.run_cli(["keys", "list", *flags]) for flags in OUTPUT_MODES}

    def loc_stack_trace(self, name, text):
        err = io.StringIO()
        with contextlib.redirect_stderr(err), boundary.install():
            try:
                raise RuntimeError("처리하지 못한 오류 " + text)
            except RuntimeError:
                sys.excepthook(*sys.exc_info())
        return {"sys.excepthook": err.getvalue()}

    def loc_doctor(self, name, text):
        failing = mock.patch.object(doctor, "_check_version", side_effect=AppError("FILE_WRITE_FAILED", {"경로": text}, detail=text))
        old_git = self.ctx.git
        self.ctx.git = lambda cwd, args: GitResult(0, text + "\n", "")                  # git 의 출력이 진단 한 줄에 그대로 실린다
        try:
            return {"doctor": self.run_cli(["doctor"], patches=[failing]), "doctor --json": self.run_cli(["--json", "doctor"], patches=[failing])}
        finally:
            self.ctx.git = old_git

    def loc_connection_test(self, name, text):
        result = cn.TestResult(False, "not_ready", message=text)
        patch = mock.patch.object(cn, "test_entry", return_value=result)
        return {"keys test": self.run_cli(["keys", "test", "1"], patches=[patch]), "keys test --json": self.run_cli(["--json", "keys", "test", "1"], patches=[patch]), "문장": "\n".join(mask(line) for line in fmt.keys_test_lines(result))}

    @staticmethod
    def text_paths(text):
        """같은 글을 가리는 모든 길."""
        stream_out = io.StringIO()
        stream = boundary.RedactingStream(stream_out)
        stream.write(text)
        stream.write("\n")
        stream.finish()
        return {"mask": mask(text), "safe_detail": safe_detail(text), "mask_block": cli.mask_block(text + "\n" + text), "스트림 래퍼": stream_out.getvalue(), "log_line": AppError("X", detail=text).log_line()}

    def loc_url_query(self, name, text):
        return self.text_paths(text)

    def loc_header(self, name, text):
        return self.text_paths(text)

    def loc_ui_message(self, name, text):
        state = app_state.AppState()
        state.apply_failure(JobFailure(text, code=text))
        view = state.home_view()["error"]
        policy = ToastPolicy()
        return {"display_text": display_text(text), "토스트": policy.offer(text)[1], "clean_failure": repr(vars(app_state.clean_failure(JobFailure(text, code=text)))), "진단 정보": app_state.diagnostic_text(JobFailure("x", code=text)),
                "예외 한 줄": app_state.unexpected_line(RuntimeError, RuntimeError(text)), "홈 오류 상태": view["user"] + view["diag"]}

    def loc_test_failure(self, name, text):
        canary = canary_of(name)
        message = sec.failure_message(canary, "앞 글 " + text + " 뒤 글", what="시험 출력")
        self.assertIsNotNone(message, "도우미가 새는 출력을 못 찾았다")
        return {"도우미 실패 메시지": message}

    def loc_workflow(self, name, text):
        env_name = re.sub(r"[^A-Z0-9]+", "_", name.upper())
        bad = f"jobs:\n  go:\n    steps:\n      - name: s\n        env:\n          {env_name}: " + "${{ secrets." + env_name + " }}\n        run: |\n          echo \"$" + env_name + "\"\n"
        self.assertTrue(wf.secret_output_problems(bad), f"{name}: 비밀을 echo 하는 합성 워크플로를 규칙이 못 잡았다")
        return {}                                                                       # 이 위치의 '출력'은 규칙이 합성 예를 잡았다는 확인 자체다 — 샐 글이 없다

    LOCATION_RUNNERS = {"일반 로그": ("loc_general_log", "assign"), "오류 로그": ("loc_error_log", "assign"), "예외 문구": ("loc_exception_text", "assign"), "스택 추적": ("loc_stack_trace", "assign"),
                        "진단 정보(doctor)": ("loc_doctor", "assign"), "연결 시험 결과": ("loc_connection_test", "assign"), "URL 질의": ("loc_url_query", "query"), "요청 헤더": ("loc_header", "header"),
                        "UI 메시지": ("loc_ui_message", "assign"), "시험 실패 출력": ("loc_test_failure", "assign"), "워크플로 산출물": ("loc_workflow", "assign")}

    def build_table(self):
        """{(위치, 이름): 샌 경로 이름들의 목록 또는 None(해당 없음)}."""
        table = {}
        for location in LOCATIONS:
            method, form = self.LOCATION_RUNNERS[location]
            for name in NAMES:
                if (location, name) in NOT_APPLICABLE:
                    table[(location, name)] = None
                    continue
                canary = canary_of(name)
                outputs = getattr(self, method)(name, carrier(name, canary, form))
                table[(location, name)] = [path for path, output in outputs.items() if sec.find_leak(canary, output) is not None]
        return table

    def test_no_name_leaks_at_any_of_the_eleven_places(self):
        table = self.build_table()
        leaks = sorted((location, name, path) for (location, name), paths in table.items() for path in (paths or []))
        self.assertEqual(leaks, [], "새는 칸이 있다(위치, 이름, 경로 이름) — 값은 적지 않는다")
        self.assertEqual(sum(1 for paths in table.values() if paths is None), len(NOT_APPLICABLE))
        self.assertEqual(len(table), len(LOCATIONS) * len(NAMES))

    def test_the_canaries_are_all_different_and_look_like_canaries(self):
        canaries = [canary_of(name) for name in NAMES]
        self.assertEqual(len(set(canaries)), len(NAMES))
        self.assertTrue(all(canary.startswith("CANARY_") for canary in canaries))

    def test_the_matrix_can_fail_a_cell_that_leaks_would_be_found(self):
        """대조 — 가리지 않고 그대로 내보내는 경로가 있다면 표가 그 칸을 빨갛게 한다(표가 '언제나 0' 이 되는 헛시험이 아니다)."""
        name = "serviceKey"
        canary = canary_of(name)
        raw = carrier(name, canary, "assign")
        self.assertIsNotNone(sec.find_leak(canary, raw), "날것의 글에서는 카나리가 보여야 한다")
        self.assertIsNone(sec.find_leak(canary, mask(raw)), "가린 글에서는 카나리가 없어야 한다")

    def test_a_real_process_with_debug_prints_no_name_in_its_traceback(self):
        """스택 추적 위치의 진짜 프로세스 확인 — 11개 이름 카나리를 한 예외 글에 넣고 `--debug` 로 되던지게 한다(진짜 진입점 `runpy` 로)."""
        canaries = {name: canary_of(name) for name in NAMES}
        text = " / ".join(carrier(name, canaries[name], "assign") for name in NAMES)
        driver = textwrap.dedent("""
            import os, runpy, sys
            sys.path.insert(0, os.environ["PCSEC1_SRC"])
            from unittest import mock
            from chanceblog_desktop.service import cli

            def boom(*args, **kwargs):
                raise RuntimeError("치명적 오류 " + os.environ["PCSEC1_TEXT"])

            with mock.patch.object(cli, "make_context", boom):
                sys.argv = ["chanceblog_desktop", "list", "--debug"]
                runpy.run_module("chanceblog_desktop", run_name="__main__", alter_sys=True)
        """)
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "driver.py"
            script.write_text(driver, encoding="utf-8")
            env = {key: value for key, value in os.environ.items() if key not in ("CHANCEBLOG_LOCAL_REPO", "CHANCEBLOG_DESKTOP_DATA")}
            env.update({"PCSEC1_SRC": str(ROOT / "src"), "PCSEC1_TEXT": text, "LOCALAPPDATA": str(Path(tmp) / "local"), "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1"})
            done = subprocess.run([sys.executable, "-X", "utf8", str(script)], capture_output=True, env=env, cwd=tmp, timeout=180)
        output = done.stdout.decode("utf-8", "replace") + done.stderr.decode("utf-8", "replace")
        self.assertEqual(done.returncode, 1)
        self.assertIn("RuntimeError", output)
        for name, canary in canaries.items():
            sec.assert_no_secret(self, canary, output, f"진짜 프로세스의 추적 — {name}")


def render_table(table):
    """결과 표(위치 × 이름) 글 — 새는 칸 0, 해당 없음은 n/a."""
    header = "| 위치 | " + " | ".join(NAMES) + " |"
    lines = [header, "|---|" + "---|" * len(NAMES)]
    for location in LOCATIONS:
        cells = []
        for name in NAMES:
            paths = table[(location, name)]
            cells.append("n/a" if paths is None else str(len(paths)))
        lines.append(f"| {location} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


if __name__ == "__main__":
    unittest.main()
