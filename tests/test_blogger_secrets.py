"""Blogger 비밀·토큰 경로의 적대 시험 — BLOGGER 설계서 BT-33–36 과 7절 '비밀 경로' 탐침(결정 D-774).

로그인 한 바퀴·연결 확인·초안 저장·여러 가지 실패·연결 해제·백업을 돌린 뒤 **이 시험이 만든 모든 파일**(데이터 폴더·임시 폴더·백업)과 **돌려받은 모든 글**(오류의 모든 표면·결과 객체의 글 모양·명령줄 출력·표준 출력·표준 오류·접속 기록)을
훑어 카나리(가짜 인증 코드·`state`·검증기·접근 토큰·갱신 토큰·클라이언트 시크릿·서버가 보낸 글)가 **하나도 없음**을 본다. 보관소(가짜 보관소 메모리)만이 값을 가질 수 있다.
"""
import contextlib
import io
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import blogger_flow_support as fs  # noqa: E402
import blogger_support as bs  # noqa: E402

from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.publish import blogger_auth as auth  # noqa: E402
from chanceblog_desktop.security.keystore import MemoryStore  # noqa: E402
from chanceblog_desktop.service import blogger_flow as flow  # noqa: E402
from chanceblog_desktop.service import cli  # noqa: E402
from chanceblog_desktop.service import connections as cn  # noqa: E402
from chanceblog_desktop.service import projects  # noqa: E402

VERIFIER = "CANARY_VERIFIER_" + "v" * 30
STATE = "CANARY_STATE_" + "s" * 30


class Recording(dict):
    """가짜 구글의 사전 — 값이 들어올 때마다 이름표와 함께 기록해 둔다(나중에 지워져도 훑기가 그 값을 찾는다)."""

    def __init__(self, sink, label):
        super().__init__()
        self.sink, self.label = sink, label

    def __setitem__(self, key, value):
        self.sink[f"{self.label} {len(self.sink)}"] = key
        super().__setitem__(key, value)


def surfaces(error):
    shown = error.rendered()
    return [error.code, repr(error.slots), str(error.detail), shown.message, shown.action, shown.retry_text, repr(error), str(error), error.log_line() if hasattr(error, "log_line") else "", repr(getattr(error, "__dict__", {}))]


class SecretsCase(fs.FlowCase):
    def setUp(self):
        super().setUp()
        for target, value in ((auth, "new_verifier"), (auth, "new_state")):
            patcher = mock.patch.object(target, value, lambda value=value: VERIFIER if value == "new_verifier" else STATE)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.seen = []                                              # 시험이 돌려받은 모든 글(오류의 표면·출력)
        self.ever = {}                                              # 가짜 구글이 만들어 준 모든 값(인증 코드·갱신 토큰·접근 토큰) — 지워진 뒤에도 남는다
        self.google.codes = Recording(self.ever, "인증 코드")
        self.google.refresh_tokens = Recording(self.ever, "갱신 토큰")
        self.google.access_tokens = Recording(self.ever, "접근 토큰")
        self.stdout, self.stderr = io.StringIO(), io.StringIO()
        out = contextlib.redirect_stdout(self.stdout)
        err = contextlib.redirect_stderr(self.stderr)
        out.__enter__()
        err.__enter__()
        self.addCleanup(out.__exit__, None, None, None)
        self.addCleanup(err.__exit__, None, None, None)

    def attempt(self, call):
        try:
            return call()
        except AppError as error:
            self.seen += surfaces(error)
            return error

    def canaries(self):
        found = {"클라이언트 시크릿(영문)": fs.CLIENT_SECRET, "클라이언트 시크릿(한글)": fs.CLIENT_SECRET_KO, "검증기": VERIFIER, "state": STATE, "서버 문장": "CANARY_SERVER", "브라우저 오류": "CANARY_BROWSER_ERROR"}
        found.update(self.ever)
        for slot in self.clients:
            try:
                blob = self.store.get(self.entry(slot).ref)
            except AppError:
                continue
            if blob is not None and "refresh_token" in blob:
                found[f"저장된 갱신 토큰 {slot}"] = blob.reveal("refresh_token")
        return found

    def sweep(self):
        """시험 폴더 아래 모든 파일(바이트)과 돌려받은 글에서 카나리를 찾는다 → 걸린 (이름, 어디) 목록."""
        canaries = self.canaries()
        hits = []
        for path in sorted(self.tmp.rglob("*")):
            if path.is_file():
                data = path.read_bytes()
                text = data.decode("utf-8", "replace") + data.decode("utf-16-le", "replace")
                hits += [(name, path.relative_to(self.tmp).as_posix()) for name, value in canaries.items() if value in text]
        everything = "\n".join(self.seen + [self.stdout.getvalue(), self.stderr.getvalue(), " ".join(repr(record) for record in self.env.usage.records()), repr(flow._ACCESS)])
        hits += [(name, "돌려받은 글·출력·접속 기록") for name, value in canaries.items() if value in everything]
        return hits


class FullRunTest(SecretsCase):
    def test_canary_code_state_tokens_never_reach_logs_errors_records_or_backups(self):
        """BT-33·34 — 로그인·갱신·초안 저장·연결 확인·실패들·연결 해제·백업을 지난 뒤 파일 시스템 전체와 돌려받은 글에서 카나리 0."""
        browser = fs.FakeBrowser(self.google, "wrong_state_then_allow")
        flow.login(self.ctx, "blogger_en", open_url=browser)
        browser.join()
        for response in browser.responses:
            self.seen.append(response.decode("latin-1"))
        flow.check(self.ctx, "blogger_en", confirmed=True)
        pid = self.approve("blogger_en")
        result = self.save(pid)
        self.seen += [repr(result), str(result), json.dumps(result.to_dict(), ensure_ascii=False)]
        self.advance(minutes=2)
        # 실패들 — 모든 오류의 모든 표면이 같은 카나리 검사를 받는다
        flow.forget()
        self.google.access_tokens.clear()
        self.google.push("insert", bs.google_error(503), bs.google_error(401))
        failing = [self.approve("blogger_en", f"실패 글 {number}") for number in range(3)]
        for mode, make in (("unknown", lambda: self.save(failing[0])), ("auth", lambda: self.save(failing[1]))):
            self.cool()
            self.attempt(make)
            self.advance(minutes=2)
        self.google.mode["insert"] = "ignore_draft"
        self.cool()
        self.attempt(lambda: self.save(failing[2]))
        self.google.mode["insert"] = "ok"
        for mode in ("invalid_grant", "invalid_client", "no_refresh", "scope_narrow", "bad_type", "status:503"):
            self.google.mode["token"] = mode
            self.cool()
            self.advance(minutes=2)
            self.attempt(lambda: self.login("blogger_ko"))
        self.google.mode["token"] = "ok"
        self.attempt(lambda: flow.login(self.ctx, "blogger_ko", open_url=fs.FakeBrowser(self.google, "broken")))
        self.attempt(lambda: flow.login(self.ctx, "blogger_ko", open_url=fs.FakeBrowser(self.google, "deny")))
        self.cool()
        self.advance(minutes=2)
        self.google.push("revoke", bs.DISCONNECT)
        self.attempt(lambda: flow.disconnect(self.ctx, "blogger_en", confirmed=True))
        self.cool()
        self.advance(minutes=2)
        disconnected = flow.disconnect(self.ctx, "blogger_en", confirmed=True)
        self.seen += [repr(disconnected), json.dumps(disconnected.to_dict(), ensure_ascii=False)]
        projects.backup_store(self.ctx)
        self.seen.append(json.dumps(cn.diagnostic_summary(self.ctx), ensure_ascii=False))
        self.assertGreater(len(self.canaries()), 5)
        self.assertEqual(self.sweep(), [])
        self.assertClean()

    def test_the_command_line_never_prints_a_secret_in_any_mode(self):
        out_all = []
        for argv in (("blogger", "status"), ("--json", "blogger", "status"), ("--verbose", "blogger", "check", "영문"), ("--json", "--verbose", "blogger", "check", "영문", "--yes"), ("keys", "list"), ("--json", "keys", "list"),
                     ("keys", "usage"), ("doctor",)):
            out, err = io.StringIO(), io.StringIO()
            if argv[-1] in ("영문",) or "check" in argv:
                if not flow.status(self.ctx, "blogger_en").logged_in:
                    self.login()
            cli.main(list(argv), out=out, err=err, ctx=self.ctx, env={}, stdin=io.StringIO(""))
            out_all += [out.getvalue(), err.getvalue()]
        self.seen += out_all
        self.assertEqual(self.sweep(), [])

    def test_the_log_line_and_the_diagnostic_text_of_every_error_hide_the_secrets(self):
        from chanceblog_desktop.security.boundary import mask_block
        self.login()
        flow.forget()
        self.google.refresh_tokens.clear()
        error = self.attempt(lambda: flow.check(self.ctx, "blogger_en"))
        self.assertIsInstance(error, AppError)
        for text in self.seen:
            masked = mask_block(text)
            self.assertNotIn(fs.CLIENT_SECRET, masked)
        self.assertEqual(self.sweep(), [])


class KeystoreTest(SecretsCase):
    def test_no_file_fallback_when_the_keystore_is_unavailable(self):
        """BT-35 — 보관소가 없으면 로그인을 시작하지 않고, 쓰기에 실패하면 어디에도 값을 남기지 않는다."""
        opened = []

        class Broken(MemoryStore):
            def get(self, ref):
                raise AppError("KEY_STORE_UNAVAILABLE", detail="시험")

        files = sorted(path.relative_to(self.tmp).as_posix() for path in self.tmp.rglob("*") if path.is_file())
        error = self.attempt(lambda: flow.login(self.ctx, "blogger_en", open_url=opened.append, keystore=Broken()))
        self.assertEqual(error.code, "KEY_STORE_UNAVAILABLE")
        self.assertEqual((opened, self.google.requests), ([], []))
        self.assertEqual(sorted(path.relative_to(self.tmp).as_posix() for path in self.tmp.rglob("*") if path.is_file()), files, "파일을 만들지 않았다")
        real = MemoryStore.put
        calls = []

        def failing(store, ref, fields):
            calls.append(sorted(fields))
            if "refresh_token" in fields:
                raise AppError("KEY_STORE_UNAVAILABLE", detail="시험용 쓰기 실패")
            return real(store, ref, fields)

        browser = fs.FakeBrowser(self.google)
        with mock.patch.object(MemoryStore, "put", failing):
            error = self.attempt(lambda: flow.login(self.ctx, "blogger_en", open_url=browser))
        browser.join()
        self.assertEqual(error.code, "KEY_STORE_UNAVAILABLE")
        self.assertEqual(flow.status(self.ctx, "blogger_en").logged_in, False)
        self.assertEqual(sorted(self.store.get(self.entry("blogger_en").ref).names()), ["client_id", "client_secret"])
        self.assertNotIn(self.entry("blogger_en").entry_id, flow._ACCESS, "저장에 실패한 로그인의 접근 토큰도 남기지 않는다")
        self.assertEqual(self.sweep(), [])

    def test_a_reading_failure_of_the_keystore_during_a_save_never_sends_and_never_writes_a_file(self):
        self.login()
        pid = self.approve("blogger_en")
        self.google.requests.clear()
        broken = mock.Mock()
        broken.get.side_effect = AppError("KEY_STORE_UNAVAILABLE", detail="시험")
        error = self.attempt(lambda: flow.save_draft(self.ctx, pid, "blogger_en", confirmed=True, keystore=broken))
        self.assertEqual((error.code, self.google.requests, self.journals()), ("KEY_STORE_UNAVAILABLE", [], []))

    def test_the_access_token_is_memory_only_and_dropped_on_disconnect(self):
        """BT-36 — `repr`·`str`·`format` 에 값이 없고, 연결 해제로 사라진다."""
        self.login()
        entry = self.entry("blogger_en")
        token = flow._ACCESS[entry.entry_id]
        for shown in (repr(token), str(token), f"{token}", repr(flow._ACCESS), str(flow._ACCESS), repr({"t": token})):
            self.assertNotIn(token.reveal(), shown)
        self.assertNotIn(token.reveal(), "\n".join(path.read_bytes().decode("utf-8", "replace") for path in self.tmp.rglob("*") if path.is_file()))
        flow.disconnect(self.ctx, "blogger_en", confirmed=True)
        self.assertNotIn(entry.entry_id, flow._ACCESS)


if __name__ == "__main__":
    unittest.main()
