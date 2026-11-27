"""`scripts/update_sign.py`(릴리스 서명 도구, RELEASE 설계서 3-5·R-1, V1REL12) 시험 — **개인키 값이 어디에도 새지 않는다**가 가장 중요하고, 서명기가 RFC 8032 와 같은 서명을 내며 앱의 검증기가 받아들이는지 본다.

지키는 것:
  1) 서명기(표준 라이브러리 구현, 앱 `update/ed25519.py` 는 검증 전용 그대로)가 RFC 8032 7.1 의 공개 시험 벡터와 같은 공개키·서명을 낸다. 시험 안의 참고 서명기(아핀 좌표, 도구와 따로 쓴 구현)와 무작위 쌍에서 같고,
     `openssl` 이 있으면 `openssl` 의 서명과도 같다(서명은 결정적이다). 앱의 검증기가 참으로 보고 한 비트를 바꾸면 거짓이다.
  2) 씨앗 형식 둘(base64 한 줄 44글자·OpenSSL PKCS#8 PEM)을 읽고, 틀린 형식은 **고정 문장**으로 거절한다.
  3) 비밀 누출 0 — 카나리 씨앗(시험이 도는 때 조립)이 표준 출력·표준 오류·예외 글·로그·`openssl` 인자와 임시 파일·서명 파일 어디에도 없다(형식이 틀린 입력·실패 길 포함).
  4) 서명 전에 앱과 같은 검사(`manifest.read_structure`·`validate_fields`)를 하고 걸리면 서명하지 않는다. 키 이름표가 매니페스트와 다르면 서명하지 않는다.
  5) 자체 검증 둘: 앱의 검증기(내장 키 목록·이 키)와 `openssl` 독립 확인. 하나라도 실패하면 종료 코드로 멈추고 서명 파일을 남기지 않는다. 내장 키 목록이 비어 있으면 고정 문장 경고(`--require-shipped-key` 면 실패).
  6) 재작업 1(안전 검증 S): `openssl` 하위 프로세스는 서명 키 변수를 받지 않는다 — 환경은 허용 목록뿐·실행 파일은 `PATH` 의 절대 경로 항목에서만(윈도는 `openssl.exe` 만)·공개 파일만 든 빈 임시 폴더에서 표준 입력 없이 돈다(S-1).
     서명 단계가 불러오는 앱 모듈은 정확히 13개(S-5). 서명 파일은 덮어쓰기를 요청하지 않으면 `O_EXCL` 로 만든다(참고 N-1).
네트워크·실제 시크릿 없이 돈다(키는 모두 시험 안의 임시 값).
"""
import ast
import base64
import errno
import hashlib
import io
import json
import os
import random
import re
import string
import subprocess
import sys
import traceback
import unittest
from functools import lru_cache
from pathlib import Path
from unittest import mock

import release_tools_support as rts
import update_support as us

from chanceblog_desktop.update import ed25519, keys, manifest

import update_sign

ROOT = rts.ROOT
SCRIPT = ROOT / "scripts" / "update_sign.py"
OPENSSL = us.openssl_path()
run_tool = rts.Capture(update_sign.main)
KEY_MESSAGE = "서명 키의 형식을 알아볼 수 없다"


@lru_cache(maxsize=None)
def pub_of(label):
    return rts.public_of(rts.canary_seed(label))


def no_openssl(_name):
    return None


def fake_openssl(_name):
    return "openssl"


def manifest_file(folder, seed, **changes):
    path = Path(folder) / "update-manifest.json"
    path.write_bytes(rts.manifest_bytes(seed, **changes))
    return path


def environ_for(seed_text):
    return {update_sign.ENV_NAME: seed_text}


class RfcVectorTest(unittest.TestCase):
    def test_test_1_of_rfc_8032_section_7_1_is_reproduced_from_a_literal_in_this_file(self):
        """RFC 8032 7.1 TEST 1 의 공개 값(씨앗·공개키·빈 메시지·서명) — 공유 상수가 아니라 이 파일에 적은 글자 그대로의 값이다."""
        seed = bytes.fromhex("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60")
        public = bytes.fromhex("d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a")
        signature = bytes.fromhex("e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b")
        self.assertEqual(update_sign.public_key(seed), public)
        self.assertEqual(update_sign.sign(seed, b""), signature)

    def test_the_five_rfc_vectors_of_the_shared_constants_are_reproduced(self):
        vectors = us.RFC_VECTORS + (us.RFC_VECTOR_1023,)
        self.assertEqual(sorted(len(bytes.fromhex(item[2])) for item in vectors), [0, 1, 2, 64, 1023])
        for index, (seed, pub, message, signature) in enumerate(vectors):
            with self.subTest(vector=index):
                seed, pub, message, signature = (bytes.fromhex(item) for item in (seed, pub, message, signature))
                self.assertEqual(update_sign.public_key(seed), pub)
                self.assertEqual(update_sign.sign(seed, message), signature)
                self.assertTrue(ed25519.verify(pub, message, signature), "앱의 검증기가 같은 서명을 참으로 본다")

    def test_the_group_constants_are_the_rfc_ones(self):
        self.assertEqual(update_sign.P, 2 ** 255 - 19)
        self.assertEqual(update_sign.L, 2 ** 252 + 27742317777372353535851937790883648493)
        self.assertEqual(update_sign.L, ed25519.L)
        self.assertEqual(update_sign.P, ed25519.P)
        base = update_sign._BASE
        self.assertEqual((base[0], base[1]), (us.RFC_BASE_X, us.RFC_BASE_Y))
        self.assertEqual(update_sign._encode(update_sign._multiply(update_sign.L, base)), update_sign._encode(update_sign._IDENTITY), "기본점에 L 을 곱하면 항등원")


class CrossCheckTest(unittest.TestCase):
    def test_random_signatures_equal_the_independent_reference_signer_of_the_tests(self):
        rng = random.Random(8032)
        for count in range(10):
            seed = bytes(rng.getrandbits(8) for _ in range(32))
            message = bytes(rng.getrandbits(8) for _ in range(rng.choice((0, 1, 31, 32, 33, 64, 200, 1023))))
            with self.subTest(count=count, length=len(message)):
                self.assertEqual(update_sign.public_key(seed), us.public_key(seed))
                self.assertEqual(update_sign.sign(seed, message), us.sign(seed, message))

    def test_every_signature_is_accepted_by_the_apps_verifier_and_a_changed_bit_is_refused(self):
        seed = rts.canary_seed("verify")
        public = update_sign.public_key(seed)
        message = update_sign.signing_message(b'{"hello": "world"}\n')
        signature = update_sign.sign(seed, message)
        self.assertEqual(len(signature), 64)
        self.assertTrue(ed25519.verify(public, message, signature))

        def flipped(data, index):
            changed = bytearray(data)
            changed[index // 8] ^= 1 << (index % 8)
            return bytes(changed)
        for index in (0, 7, 100, 255, 256, 300, 511):
            self.assertFalse(ed25519.verify(public, message, flipped(signature, index)), f"서명 비트 {index}")
        for index in (0, 8 * len(message) - 1, 8 * 5):
            self.assertFalse(ed25519.verify(public, flipped(message, index), signature), f"메시지 비트 {index}")
        self.assertFalse(ed25519.verify(flipped(public, 3), message, signature))
        self.assertFalse(ed25519.verify(public, message[:-1], signature))

    def test_signing_is_deterministic_and_depends_on_the_seed_and_the_message(self):
        seed = rts.canary_seed("det")
        self.assertEqual(update_sign.sign(seed, b"a"), update_sign.sign(seed, b"a"))
        self.assertNotEqual(update_sign.sign(seed, b"a"), update_sign.sign(seed, b"b"))
        self.assertNotEqual(update_sign.sign(seed, b"a"), update_sign.sign(rts.canary_seed("det2"), b"a"))

    @unittest.skipIf(OPENSSL is None, "건너뜀: openssl 3.x 가 없다 — 교차 확인은 openssl 이 있는 칸에서만")
    def test_openssl_makes_the_same_signature_and_verifies_ours(self):
        rng = random.Random(25519)
        for count in range(4):
            seed = bytes(rng.getrandbits(8) for _ in range(32))
            message = bytes(rng.getrandbits(8) for _ in range(rng.choice((1, 33, 200))))
            with self.subTest(count=count):
                theirs, their_pub = us.openssl_sign(seed, message, OPENSSL)
                self.assertEqual(update_sign.public_key(seed), their_pub)
                self.assertEqual(update_sign.sign(seed, message), theirs, "서명은 결정적이라 같아야 한다")
                self.assertTrue(us.openssl_verify(update_sign.public_key(seed), message, update_sign.sign(seed, message), OPENSSL))

    def test_key_id_matches_the_app(self):
        public = pub_of("kid")
        self.assertEqual(update_sign.key_id_of(public), keys.key_id_of(public))
        self.assertRegex(update_sign.key_id_of(public), r"[0-9a-f]{16}")


class KeyFormatTest(unittest.TestCase):
    def test_raw_base64_and_pem_in_any_line_ending_give_the_same_seed(self):
        seed = rts.canary_seed("fmt")
        b64, pem = rts.seed_b64(seed), rts.seed_pem(seed)
        self.assertEqual(len(b64), 44)
        for text in (b64, b64 + "\n", "  " + b64 + " \r\n", pem, pem.strip(), rts.seed_pem(seed, crlf=True), "\n" + pem):
            with self.subTest(text=text[:6]):
                self.assertEqual(update_sign.parse_signing_key(text), seed)

    def test_the_two_formats_of_one_seed_give_one_public_key(self):
        seed = rts.canary_seed("same")
        first = update_sign.public_key(update_sign.parse_signing_key(rts.seed_b64(seed)))
        second = update_sign.public_key(update_sign.parse_signing_key(rts.seed_pem(seed)))
        self.assertEqual(first, second)
        self.assertEqual(first, pub_of("same"))

    def bad_texts(self):
        seed = rts.canary_seed("bad")
        b64 = rts.seed_b64(seed)
        alphabet = string.ascii_uppercase + string.ascii_lowercase + string.digits + "+/"
        non_canonical = b64[:42] + alphabet[alphabet.index(b64[42]) ^ 1] + "="        # 마지막 글자의 남는 비트가 0 이 아닌 base64(읽히기는 하지만 정규 형태가 아니다)
        pem = rts.seed_pem(seed)
        der = bytes.fromhex("302e020100300506032b657004220420") + seed
        label = "PRIVATE " + "KEY"

        def pem_of(raw, word=label):
            return "-----BEGIN " + word + "-----\n" + base64.b64encode(raw).decode() + "\n-----END " + word + "-----\n"
        return {
            "empty": "", "blank": " \n ", "short": b64[:-1], "long": b64 + "A", "no padding": b64.rstrip("="), "bad alphabet": b64[:10] + "!" + b64[11:], "inner space": b64[:20] + " " + b64[20:],
            "urlsafe": b64.replace("+", "-").replace("/", "_") if ("+" in b64 or "/" in b64) else b64[:-1] + "_", "hex": seed.hex(), "non canonical": non_canonical,
            "31 bytes": base64.b64encode(seed[:31]).decode(), "33 bytes": base64.b64encode(seed + b"x").decode(), "two lines": b64 + "\n" + b64,
            "wrong label": pem_of(der, "EC " + label), "encrypted label": pem_of(der, "ENCRYPTED " + label), "public label": pem_of(der, "PUBLIC KEY"),
            "x25519 oid": pem_of(bytes.fromhex("302e020100300506032b656e04220420") + seed), "short der": pem_of(der[:-1]), "long der": pem_of(der + b"\x00"), "seed only": pem_of(seed),
            "no end": pem.rsplit("-----END", 1)[0], "extra header": pem.replace("\n", "\nProc-Type: 4,ENCRYPTED\n", 1), "nul": b64 + "\x00", "huge": "A" * 100000,
            "pem inside text": "x " + pem, "two pems": pem + pem,
        }

    def test_every_bad_form_is_refused_with_the_one_fixed_sentence(self):
        for name, text in self.bad_texts().items():
            with self.subTest(form=name):
                with self.assertRaises(update_sign.SigningKeyError) as raised:
                    update_sign.parse_signing_key(text)
                self.assertEqual(str(raised.exception), KEY_MESSAGE)
                self.assertEqual(raised.exception.args, (KEY_MESSAGE,))

    def test_non_text_input_is_refused_too(self):
        for value in (None, b"abc", 12, ["x"]):
            with self.subTest(value=repr(value)):
                with self.assertRaises(update_sign.SigningKeyError):
                    update_sign.parse_signing_key(value)

    def test_the_refusal_carries_no_trace_of_the_value_in_text_args_repr_chain_or_traceback(self):
        seed = rts.canary_seed("bad")                      # `bad_texts` 가 쓰는 씨앗 — 틀린 값 대부분이 이 씨앗을 품고 있다
        extra = {"canary plus one": rts.seed_b64(seed) + "A", "canary pem plus x": rts.seed_pem(seed) + "x"}
        for name, text in {**self.bad_texts(), **extra}.items():
            with self.subTest(form=name):
                try:
                    update_sign.parse_signing_key(text)
                except update_sign.SigningKeyError as error:
                    shown = "".join(traceback.format_exception(type(error), error, error.__traceback__))
                    rts.assert_no_leak(self, seed, str(error), repr(error), repr(error.args), shown)
                    self.assertIsNone(error.__cause__)
                    self.assertTrue(error.__suppress_context__, "원래 오류(값이 든 것)를 이어 붙이지 않는다")
                else:
                    self.fail("거절돼야 한다")


class SecretHygieneTest(unittest.TestCase):
    """가장 중요한 시험 — 카나리 씨앗이 어느 길로도 밖으로 나가지 않는다."""

    def run_with(self, seed_text, seed, folder, extra=(), **kwargs):
        path = manifest_file(folder, seed)
        runner = rts.FakeRun(rts.ok_process)
        kwargs.setdefault("shipped", keys.Keyring())
        with self.assertNoLogs(level="DEBUG"):
            code, out, err = run_tool(["--manifest", str(path), *extra], environ=environ_for(seed_text), which=fake_openssl, run=runner, **kwargs)
        return code, out, err, runner, path

    def test_a_good_run_leaks_nothing_into_output_logs_openssl_arguments_files_or_the_signature_file(self):
        seed = rts.canary_seed("hyg1")
        for text in (rts.seed_b64(seed), rts.seed_pem(seed)):
            with rts.temp_dir() as folder:
                code, out, err, runner, path = self.run_with(text, seed, folder)
                self.assertEqual(code, 0, err)
                rts.assert_no_leak(self, seed, out, err, "\n".join(" ".join(command) for command, _ in runner.calls), b"\n".join(runner.file_texts), (path.parent / "update-manifest.json.sig").read_bytes(),
                                   repr(runner.calls))
                self.assertEqual(len(runner.calls), 1)
                self.assertTrue(runner.file_texts, "openssl 에 넘긴 파일(공개키·메시지·서명)은 있다 — 비밀은 그 안에 없다")

    def test_the_output_is_exactly_the_fixed_text_so_not_even_one_extra_character_can_be_added(self):
        seed = rts.canary_seed("hyg2")
        with rts.temp_dir() as folder:
            code, out, err, _runner, _path = self.run_with(rts.seed_b64(seed), seed, folder)
        ident = rts.key_id(pub_of("hyg2"))
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        self.assertEqual(out, "서명했다: update-manifest.json.sig\n"
                              f"키 이름표(지문): {ident}\n"
                              "자체 검증 1 · 앱과 같은 검증기, 이 서명 키의 공개키: 통과\n"
                              "자체 검증 1 · 앱에 내장된 공개키 목록: 경고 — 내장된 공개키 목록이 비어 있어 지금의 앱은 이 서명을 아직 받지 않는다\n"
                              "자체 검증 2 · openssl 독립 확인: 통과\n")

    def test_failure_paths_leak_nothing_either(self):
        seed = rts.canary_seed("hyg3")
        text = rts.seed_b64(seed)
        with rts.temp_dir() as folder:
            path = manifest_file(folder, seed)
            cases = {
                "malformed key containing the canary": dict(environ=environ_for(text + "A")),
                "pem with garbage": dict(environ=environ_for(rts.seed_pem(seed) + "x")),
                "openssl says no": dict(environ=environ_for(text), run=rts.FakeRun(rts.failing_process), which=fake_openssl),
                "wrong key id": dict(environ=environ_for(rts.seed_b64(rts.canary_seed("hyg3b"))), which=no_openssl),
                "signer raises with the value inside": dict(environ=environ_for(text), which=no_openssl, signer=lambda s, m: (_ for _ in ()).throw(RuntimeError(text + seed.hex() + repr(seed)))),
                "signer returns junk": dict(environ=environ_for(text), which=no_openssl, signer=lambda s, m: b"x" * 64),
            }
            for name, kwargs in cases.items():
                with self.subTest(case=name):
                    kwargs.setdefault("which", no_openssl)
                    with self.assertNoLogs(level="DEBUG"):
                        code, out, err = run_tool(["--manifest", str(path)], **kwargs)
                    self.assertNotEqual(code, 0)
                    rts.assert_no_leak(self, seed, out, err)
                    self.assertFalse((Path(folder) / "update-manifest.json.sig").exists(), "실패하면 서명 파일을 남기지 않는다")

    def test_an_unexpected_exception_prints_only_its_class_name(self):
        seed = rts.canary_seed("hyg4")
        with rts.temp_dir() as folder:
            path = manifest_file(folder, seed)

            def boom(_seed, _message):
                raise RuntimeError("값:" + rts.seed_b64(seed))
            code, out, err = run_tool(["--manifest", str(path)], environ=environ_for(rts.seed_b64(seed)), which=no_openssl, signer=boom)
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertEqual(err, "예상하지 못한 오류로 멈췄다(종류: RuntimeError). 서명 파일을 만들지 않았다.\n")

    def test_the_tool_never_writes_a_step_summary_or_any_other_file_than_the_signature_file(self):
        seed = rts.canary_seed("hyg5")
        with rts.temp_dir() as folder:
            path = manifest_file(folder, seed)
            summary = Path(folder) / "summary.md"
            before = sorted(item.name for item in Path(folder).iterdir())
            environ = dict(environ_for(rts.seed_b64(seed)), GITHUB_STEP_SUMMARY=str(summary), GITHUB_OUTPUT=str(Path(folder) / "output.txt"))
            code, _out, _err = run_tool(["--manifest", str(path)], environ=environ, which=no_openssl)
            after = sorted(item.name for item in Path(folder).iterdir())
        self.assertEqual(code, 0)
        self.assertEqual(sorted(set(after) - set(before)), ["update-manifest.json.sig"])

    def test_the_source_has_no_logging_no_traceback_printing_and_no_value_in_any_message(self):
        text = SCRIPT.read_text(encoding="utf-8")
        tree = ast.parse(text)
        imported = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
        imported |= {(node.module or "").split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        self.assertFalse(imported & {"logging", "traceback", "pdb", "pprint", "warnings", "faulthandler", "inspect"}, imported)
        calls = [ast.unparse(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)]
        self.assertNotIn("print", [name for name in calls], "표준 출력은 주입된 stdout 으로만 쓴다")
        self.assertFalse(any(name.endswith("print_exc") or name.endswith("format_exc") for name in calls))
        # 비밀을 담는 이름(씨앗·키 글)이 f-문자열이나 `%`·`format` 으로 메시지에 들어가는 곳이 없다
        secret_names = {"seed", "key_text", "secret", "raw_key", "text"}
        for node in ast.walk(tree):
            if isinstance(node, ast.JoinedStr):
                used = {name.id for part in ast.walk(node) for name in [part] if isinstance(part, ast.Name)}
                self.assertFalse(used & secret_names, f"f-문자열에 비밀 이름이 든다: {sorted(used & secret_names)} (줄 {node.lineno})")


class AppStaysVerifyOnlyTest(unittest.TestCase):
    def test_no_signing_code_lives_in_the_app(self):
        names = set()
        for path in sorted((ROOT / "src" / "chanceblog_desktop" / "update").glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            names |= {node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        for forbidden in ("sign", "public_key", "secret_expand", "generate", "keygen", "sign_manifest"):
            self.assertNotIn(forbidden, names, "서명 만들기는 앱 번들에 넣지 않는다 — scripts/ 의 도구 몫이다")
        self.assertFalse(hasattr(ed25519, "sign"))

    def test_the_tool_uses_the_apps_prefix_and_verifier_not_copies(self):
        self.assertIs(update_sign.SIGN_PREFIX, manifest.SIGN_PREFIX)
        self.assertEqual(update_sign.SIGN_PREFIX, b"ChanceBlogDesktop-update-manifest-v1\n")
        self.assertEqual(update_sign.signing_message(b"abc"), b"ChanceBlogDesktop-update-manifest-v1\nabc")


SIGNING_PROCESS_APP_MODULES = frozenset({
    "chanceblog_desktop", "chanceblog_desktop.errors", "chanceblog_desktop.errors.catalog", "chanceblog_desktop.errors.model", "chanceblog_desktop.errors.render",
    "chanceblog_desktop.errors.table", "chanceblog_desktop.net", "chanceblog_desktop.net.parse", "chanceblog_desktop.update", "chanceblog_desktop.update.ed25519",
    "chanceblog_desktop.update.keys", "chanceblog_desktop.update.manifest", "chanceblog_desktop.update.versions"})


class SigningProcessModulesTest(unittest.TestCase):
    """재작업 1(S-5) — 서명 단계는 앱 모듈을 **서명 키가 환경에 있는 프로세스 안에서** 불러온다. 그 집합을 못박는다: 새 앱 모듈이 슬쩍 끼면(예: 거의 모든 갈래가 고치는 `errors/catalog.py` 가 새 import 를
    끌고 오면) 빨개진다 — 의도한 변경이면 이 집합과 `docs/SECURITY.md` 의 개수(13)를 함께 고친다."""

    def loaded_app_modules(self, entry):
        code = ("import json, sys\nsys.path.insert(0, %r)\nimport %s\n"
                "print(json.dumps(sorted(name for name in sys.modules if name == 'chanceblog_desktop' or name.startswith('chanceblog_desktop.'))))\n") % (str(ROOT / "scripts"), entry)
        done = subprocess.run([sys.executable, "-X", "utf8", "-I", "-c", code], capture_output=True, timeout=120)
        self.assertEqual(done.returncode, 0, done.stderr.decode("utf-8", "replace"))
        return set(json.loads(done.stdout.decode("utf-8")))

    def test_the_signing_script_loads_exactly_these_thirteen_app_modules(self):
        loaded = self.loaded_app_modules("update_sign")
        self.assertEqual(len(SIGNING_PROCESS_APP_MODULES), 13)
        self.assertEqual(loaded, set(SIGNING_PROCESS_APP_MODULES), f"새로 올라온 앱 모듈: {sorted(loaded - SIGNING_PROCESS_APP_MODULES)} · 빠진 것: {sorted(SIGNING_PROCESS_APP_MODULES - loaded)} — "
                                                                    "서명 키가 있는 프로세스에서 도는 코드가 바뀐다(docs/SECURITY.md 의 서명 도구 절과 함께 고친다)")

    def test_the_key_variable_name_appears_in_none_of_those_app_modules(self):
        """그 집합 안의 앱 코드는 서명 키 변수를 읽지도 가리키지도 않는다 — 그 변수는 이 도구 한 곳만 읽는다."""
        for name in sorted(SIGNING_PROCESS_APP_MODULES):
            parts = name.split(".")[1:]
            path = ROOT / "src" / "chanceblog_desktop" / Path(*parts) if parts else ROOT / "src" / "chanceblog_desktop"
            file = path / "__init__.py" if path.is_dir() else path.with_suffix(".py")
            self.assertTrue(file.is_file(), name)
            self.assertNotIn("UPDATE_SIGNING_KEY", file.read_text(encoding="utf-8"), name)


class CliFlowTest(unittest.TestCase):
    def test_a_good_run_writes_the_reference_signature_in_the_88_character_line_format(self):
        seed = rts.canary_seed("flow1")
        with rts.temp_dir() as folder:
            path = manifest_file(folder, seed)
            data = path.read_bytes()
            code, out, err = run_tool(["--manifest", str(path)], environ=environ_for(rts.seed_b64(seed)), which=no_openssl)
            written = (Path(folder) / "update-manifest.json.sig").read_bytes()
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(written, us.signature_file(seed, data), "서명 파일 = 시험의 참고 서명기가 낸 접두어 + 바이트의 서명(base64 한 줄 + LF)")
        self.assertEqual(len(written), 89)
        self.assertTrue(written.endswith(b"\n") and b"\r" not in written)
        self.assertIn("건너뜀", out)
        public = pub_of("flow1")
        verified = manifest.read_and_verify(data, written, keyring=keys.Keyring([(keys.ROLE_CURRENT, public)]), channels=manifest.CHANNELS_OFFLINE)
        self.assertEqual(verified.key_id, rts.key_id(public))

    def test_the_signature_goes_next_to_the_manifest_by_default_and_to_sig_out_when_asked(self):
        seed = rts.canary_seed("flow2")
        with rts.temp_dir() as folder:
            path = manifest_file(folder, seed)
            other = Path(folder) / "other.sig"
            code, _out, _err = run_tool(["--manifest", str(path), "--sig-out", str(other)], environ=environ_for(rts.seed_b64(seed)), which=no_openssl)
            self.assertEqual(code, 0)
            self.assertTrue(other.is_file())
            self.assertFalse((Path(folder) / "update-manifest.json.sig").exists())

    def test_an_existing_signature_file_is_not_overwritten_unless_asked(self):
        seed = rts.canary_seed("flow3")
        with rts.temp_dir() as folder:
            path = manifest_file(folder, seed)
            sig = Path(folder) / "update-manifest.json.sig"
            sig.write_bytes(b"OLD\n")
            code, out, err = run_tool(["--manifest", str(path)], environ=environ_for(rts.seed_b64(seed)), which=no_openssl)
            self.assertEqual((code, sig.read_bytes()), (2, b"OLD\n"))
            self.assertEqual(err, "서명 파일이 이미 있어 쓰지 않았다(덮어쓰려면 --overwrite).\n")
            code, _out, _err = run_tool(["--manifest", str(path), "--overwrite"], environ=environ_for(rts.seed_b64(seed)), which=no_openssl)
            self.assertEqual(code, 0)
            self.assertNotEqual(sig.read_bytes(), b"OLD\n")

    def test_the_signature_may_not_be_written_over_the_manifest_itself(self):
        seed = rts.canary_seed("flow3b")
        with rts.temp_dir() as folder:
            path = manifest_file(folder, seed)
            before = path.read_bytes()
            for extra in (("--sig-out", str(path)), ("--sig-out", str(path), "--overwrite"), ("--sig-out", str(path).upper(), "--overwrite") if os.name == "nt" else ("--sig-out", str(path))):
                code, out, err = run_tool(["--manifest", str(path), *extra], environ=environ_for(rts.seed_b64(seed)), which=no_openssl)
                self.assertEqual((code, out), (2, ""))
                self.assertEqual(path.read_bytes(), before, "매니페스트는 그대로다")
            self.assertIn("서명 파일 경로가 매니페스트 파일과 같다", err)

    def test_missing_or_blank_key_variable_and_missing_manifest_stop_with_fixed_sentences(self):
        seed = rts.canary_seed("flow4")
        with rts.temp_dir() as folder:
            path = manifest_file(folder, seed)
            for environ in ({}, {update_sign.ENV_NAME: ""}, {update_sign.ENV_NAME: "  \n"}):
                code, out, err = run_tool(["--manifest", str(path)], environ=environ, which=no_openssl)
                self.assertEqual((code, out), (3, ""))
                self.assertEqual(err, "서명하지 않았다: 환경 변수 UPDATE_SIGNING_KEY 가 없거나 비어 있다.\n")
            code, out, err = run_tool(["--manifest", str(Path(folder) / "none.json")], environ=environ_for(rts.seed_b64(seed)), which=no_openssl)
            self.assertEqual((code, out, err), (2, "", "서명하지 않았다: 매니페스트 파일을 읽지 못했다.\n"))
            self.assertFalse((Path(folder) / "update-manifest.json.sig").exists())

    def test_a_bad_key_format_stops_with_the_key_sentence_and_no_file(self):
        seed = rts.canary_seed("flow5")
        with rts.temp_dir() as folder:
            path = manifest_file(folder, seed)
            code, out, err = run_tool(["--manifest", str(path)], environ=environ_for(rts.seed_b64(seed)[:-2]), which=no_openssl)
            self.assertEqual((code, out), (3, ""))
            self.assertEqual(err, "서명하지 않았다: 서명 키의 형식을 알아볼 수 없다(씨앗 base64 한 줄 44글자 또는 OpenSSL 개인키 PEM 만 읽는다).\n")
            self.assertFalse((Path(folder) / "update-manifest.json.sig").exists())

    def test_the_secret_variable_name_is_fixed_and_a_secret_given_as_an_argument_is_never_echoed(self):
        """비밀을 인자로 넘기려는 실수에도 인자 글을 되풀이하지 않는다(argparse 의 기본 오류 글은 모르는 인자를 그대로 보인다)."""
        seed = rts.canary_seed("flow6")
        text = rts.seed_b64(seed)
        for argv in (["--manifest", "x", "--key", text], ["--manifest", "x", text], ["--key=" + text], ["-h"], []):
            with self.subTest(argv=argv[:2]):
                code, out, err = run_tool(argv, environ={}, which=no_openssl)
                self.assertEqual((code, out), (2, ""))
                self.assertEqual(err, "사용법 오류: 인자를 알아볼 수 없다. 쓰는 법은 --manifest 파일 [--sig-out 파일] [--overwrite] [--require-shipped-key] [--require-openssl] 이다 — "
                                      "비밀 값은 인자로 받지 않고 환경 변수 UPDATE_SIGNING_KEY 로만 받는다.\n")
                rts.assert_no_leak(self, seed, out, err)
        self.assertEqual(update_sign.ENV_NAME, "UPDATE_SIGNING_KEY")


class PreSignCheckTest(unittest.TestCase):
    """앱이 거절할 매니페스트에는 서명하지 않는다 — 앱과 같은 코드(`manifest.read_structure`·`validate_fields`)로 서명 전에 본다."""

    def never_sign(self, seed, message):
        raise AssertionError("서명하면 안 되는 매니페스트에 서명하려 했다")

    def refused(self, data, reason=None, code=4):
        seed = rts.canary_seed("pre")
        with rts.temp_dir() as folder:
            path = Path(folder) / "update-manifest.json"
            path.write_bytes(data)
            got = run_tool(["--manifest", str(path)], environ=environ_for(rts.seed_b64(seed)), which=no_openssl, signer=self.never_sign)
            exists = (Path(folder) / "update-manifest.json.sig").exists()
        self.assertEqual(got[0], code, got)
        self.assertEqual(got[1], "")
        self.assertFalse(exists)
        if reason is not None:
            self.assertEqual(got[2], f"서명하지 않았다: 앱이 받아들이지 않을 매니페스트다(이유 이름표: {reason}).\n")
        return got

    def test_manifests_the_app_would_refuse_are_not_signed_and_the_reason_is_a_fixed_word(self):
        seed = rts.canary_seed("pre")
        good = rts.manifest_bytes(seed)
        cases = {
            "seq": rts.manifest_bytes(seed, seq=1), "schema": rts.manifest_bytes(seed, schema=2), "tag": rts.manifest_bytes(seed, tag="v9.9.9"),
            "time_span": rts.manifest_bytes(seed, expires_utc="2028-01-01T00:00:00Z"), "keys": rts.manifest_bytes(seed, extra="x"),
            "control_char": rts.manifest_bytes(seed, notes={"summary": "가" + chr(0x200D) + "나"}), "line_ending": good.replace(b"\n", b"\r\n"), "final_newline": good.rstrip(b"\n"),
            "min_version": rts.manifest_bytes(seed, min_version="2.0.0"),
        }
        for reason, data in cases.items():
            with self.subTest(reason=reason):
                self.refused(data)
        self.assertIn("(이유 이름표: seq)", self.refused(cases["seq"])[2])
        self.assertIn("(이유 이름표: control_char)", self.refused(cases["control_char"])[2])

    def test_json_the_strict_reader_refuses_is_not_signed(self):
        seed = rts.canary_seed("pre")
        good = rts.manifest_bytes(seed)
        duplicate = good.replace(b'"schema": 1,', b'"schema": 1,\n  "schema": 1,', 1)
        self.assertNotEqual(duplicate, good)
        for name, data in {"bom": b"\xef\xbb\xbf" + good, "duplicate key": duplicate, "float": good.replace(b'"seq": 20261201030000', b'"seq": 20261201030000.0'), "not json": b"hello\n", "empty": b"", "array": b"[]\n",
                           "huge": good[:-1] + b" " * (manifest.MAX_MANIFEST_BYTES + 5) + b"\n"}.items():
            with self.subTest(name=name):
                self.refused(data)

    def test_a_manifest_whose_key_id_is_another_key_is_not_signed(self):
        seed, other = rts.canary_seed("pre"), rts.canary_seed("pre-other")
        with rts.temp_dir() as folder:
            path = manifest_file(folder, other)                       # key_id 는 다른 키의 이름표
            code, out, err = run_tool(["--manifest", str(path)], environ=environ_for(rts.seed_b64(seed)), which=no_openssl, signer=self.never_sign)
            self.assertEqual((code, out), (4, ""))
            self.assertEqual(err, "서명하지 않았다: 매니페스트의 key_id 가 서명 키의 이름표와 다르다 — 키를 잘못 넣었거나 매니페스트를 다른 키 기준으로 만들었다.\n")
            self.assertFalse((Path(folder) / "update-manifest.json.sig").exists())

    def test_a_candidate_manifest_of_the_rc_channel_is_signed_because_the_offline_path_reads_it(self):
        seed = rts.canary_seed("pre-rc")
        data = rts.manifest_bytes(seed, channel="rc", version="1.0.1-rc.1", tag="v1.0.1-rc.1", min_version="1.0.0-rc.1", files=[
            {"role": "setup", "name": "ChanceBlogDesktop-1.0.1-rc.1-Setup.exe", "size": 4600, "sha256": us.HASH_A}])
        with rts.temp_dir() as folder:
            path = Path(folder) / "update-manifest.json"
            path.write_bytes(data)
            code, _out, err = run_tool(["--manifest", str(path)], environ=environ_for(rts.seed_b64(seed)), which=no_openssl)
        self.assertEqual((code, err), (0, ""))


class WriteFails:
    """쓰면 늘 같은 오류를 던지는 표준 출력·오류 흉내 — 닫힌 파이프·못 쓰는 글자."""

    def __init__(self, error):
        self.error = error
        self.tries = 0

    def write(self, text):
        self.tries += 1
        raise self.error


class FlushFails:
    """쓰기는 되는데 비우기에서 실패하는 표준 출력 흉내 — 이미 닫힌 파이프는 쓰는 순간이 아니라 비울 때 오류가 난다."""

    def __init__(self, error):
        self.error = error
        self.written = []

    def write(self, text):
        self.written.append(text)
        return len(text)

    def flush(self):
        raise self.error


class NoFlush:
    """`flush` 가 없는 글 받이 — 쓰기만 된다."""

    def __init__(self):
        self.written = []

    def write(self, text):
        self.written.append(text)
        return len(text)


class OutputSafetyTest(unittest.TestCase):
    """재작업 1(시험 렌즈 Q 의 R2) — 서명 파일을 쓴 **뒤에** 결과를 화면에 쓰다 실패해도(비 UTF-8 파이프·닫힌 파이프) '서명 파일을 만들지 않았다' 는 거짓 문장과 실제(파일이 있다)가 어긋나지 않는다:
    출력 인코딩이 못 쓰는 글자는 물음표로 바꿔 다시 쓰고(서명은 정상·종료 0), 그래도 못 쓰면 서명 파일은 그대로 두고 **다른 종료 코드(5)와 ASCII 고정 문장**으로 알린다. 파일 쓰기 실패는 따로(종료 1)."""

    def run_main(self, label, stdout, stderr, **kwargs):
        seed = rts.canary_seed(label)
        holder = rts.temp_dir()
        self.addCleanup(holder.cleanup)
        path = manifest_file(holder.name, seed)
        kwargs.setdefault("which", no_openssl)
        kwargs.setdefault("shipped", keys.Keyring())
        code = update_sign.main(["--manifest", str(path)], environ=environ_for(rts.seed_b64(seed)), stdout=stdout, stderr=stderr, **kwargs)
        return seed, code, path, Path(holder.name) / "update-manifest.json.sig"

    def test_an_output_encoding_that_cannot_write_some_characters_gets_question_marks_and_the_signature_is_fine(self):
        for encoding in ("ascii", "cp949"):
            with self.subTest(encoding=encoding):
                buffer = io.BytesIO()
                stdout = io.TextIOWrapper(buffer, encoding=encoding, errors="strict", write_through=True)
                err = io.StringIO()
                seed, code, path, sig = self.run_main("os-" + encoding, stdout, err)
                self.assertEqual((code, err.getvalue()), (0, ""))
                self.assertEqual(sig.read_bytes(), us.signature_file(seed, path.read_bytes()), "서명 파일은 정상이다")
                written = buffer.getvalue()
                self.assertIn(rts.key_id(pub_of("os-" + encoding)).encode("ascii"), written, "공개 값(지문)은 그대로 보인다")
                self.assertIn(b"?", written, "못 쓰는 글자(긴 줄표 등)는 물음표가 된다")
                if encoding == "cp949":
                    self.assertIn("서명했다".encode("cp949"), written, "쓸 수 있는 글자(한글)는 그대로다")
                else:
                    written.decode("ascii")
                rts.assert_no_leak(self, seed, written)

    def test_when_the_output_fails_for_good_the_signature_stays_and_the_code_and_the_sentence_say_so(self):
        errors = {"broken pipe": BrokenPipeError(errno.EPIPE, "broken pipe"), "os error": OSError(errno.EIO, "input output error"), "closed file": ValueError("I/O operation on closed file")}
        for label, error in errors.items():
            with self.subTest(case=label):
                err = io.StringIO()
                stdout = WriteFails(error)
                seed, code, path, sig = self.run_main("os2", stdout, err)
                self.assertEqual(update_sign.EXIT_OUTPUT, 5)
                self.assertEqual(code, update_sign.EXIT_OUTPUT)
                self.assertEqual(err.getvalue(), update_sign.MSG_OUTPUT_FAILED + "\n")
                self.assertTrue(err.getvalue().isascii(), "어떤 출력 인코딩으로도 쓸 수 있는 ASCII 고정 문장")
                self.assertNotIn("만들지 않았다", err.getvalue(), "서명 파일은 만들었다 — 거짓 문장이 아니다")
                self.assertEqual(sig.read_bytes(), us.signature_file(seed, path.read_bytes()), "서명 파일은 만들어져 있고 정상이다")
                self.assertGreaterEqual(stdout.tries, 1)
                rts.assert_no_leak(self, seed, err.getvalue())

    def test_a_failing_error_stream_never_turns_into_an_exception_on_any_path(self):
        seed, code, _path, sig = self.run_main("os3", WriteFails(OSError("x")), WriteFails(UnicodeEncodeError("ascii", "x", 0, 1, "bad")))
        self.assertEqual(code, update_sign.EXIT_OUTPUT)
        self.assertTrue(sig.is_file(), "결과를 못 써도 서명은 있다")
        holder = rts.temp_dir()
        self.addCleanup(holder.cleanup)
        path = manifest_file(holder.name, seed)
        broken = WriteFails(UnicodeEncodeError("ascii", "x", 0, 1, "bad"))
        self.assertEqual(update_sign.main(["--manifest", str(path)], environ={}, stdout=io.StringIO(), stderr=broken, which=no_openssl), update_sign.EXIT_KEY, "키 없음 오류를 못 써도 코드는 그대로")
        self.assertEqual(update_sign.main(["--bogus"], environ={}, stdout=io.StringIO(), stderr=broken, which=no_openssl), update_sign.EXIT_USAGE)
        self.assertEqual(update_sign.main(["--manifest", str(path)], environ=environ_for(rts.seed_b64(seed)), stdout=io.StringIO(), stderr=broken, which=no_openssl,
                                          signer=lambda s, m: (_ for _ in ()).throw(RuntimeError("x"))), update_sign.EXIT_FAILED, "예상 못 한 오류를 못 써도 코드는 그대로(역추적도 없다)")
        self.assertGreaterEqual(broken.tries, 3)

    def test_a_file_write_failure_is_another_code_and_still_says_no_signature_file_was_created(self):
        seed = rts.canary_seed("os4")
        with rts.temp_dir() as folder:
            path = manifest_file(folder, seed)
            err = io.StringIO()
            with mock.patch("os.fsync", side_effect=OSError("disk full")):
                code = update_sign.main(["--manifest", str(path)], environ=environ_for(rts.seed_b64(seed)), stdout=io.StringIO(), stderr=err, which=no_openssl, shipped=keys.Keyring())
            self.assertEqual((code, err.getvalue()), (update_sign.EXIT_FAILED, "예상하지 못한 오류로 멈췄다(종류: OSError). 서명 파일을 만들지 않았다.\n"))
            self.assertNotEqual(code, update_sign.EXIT_OUTPUT)
            self.assertFalse((Path(folder) / "update-manifest.json.sig").exists())

    def test_a_pipe_that_fails_only_when_flushed_is_also_an_output_failure(self):
        """닫힌 파이프는 쓰는 순간이 아니라 비울 때 오류가 난다 — 안전한 쓰기가 비우기까지 해서 '썼다' 가 거짓이 되지 않게 한다."""
        for error in (BrokenPipeError(errno.EPIPE, "broken pipe"), OSError(errno.EINVAL, "invalid argument"), ValueError("I/O operation on closed file")):
            with self.subTest(error=type(error).__name__):
                err = io.StringIO()
                seed, code, path, sig = self.run_main("os5", FlushFails(error), err)
                self.assertEqual((code, err.getvalue()), (update_sign.EXIT_OUTPUT, update_sign.MSG_OUTPUT_FAILED + "\n"))
                self.assertEqual(sig.read_bytes(), us.signature_file(seed, path.read_bytes()))

    def test_the_safe_writer_returns_true_only_when_something_was_written(self):
        sink = io.StringIO()
        self.assertTrue(update_sign.say(sink, "abc"))
        self.assertEqual(sink.getvalue(), "abc")
        plain = NoFlush()
        self.assertTrue(update_sign.say(plain, "abc"), "`flush` 가 없는 글 받이도 쓰기만 되면 된다")
        self.assertEqual(plain.written, ["abc"])
        self.assertFalse(update_sign.say(FlushFails(OSError("x")), "abc"), "비우기에서 실패하면 쓴 것이 아니다")
        narrow = io.TextIOWrapper(io.BytesIO(), encoding="ascii", errors="strict", write_through=True)
        self.assertTrue(update_sign.say(narrow, "a — 한글 b"))
        self.assertEqual(narrow.buffer.getvalue(), b"a ? ?? b")
        self.assertFalse(update_sign.say(WriteFails(OSError("x")), "abc"))
        self.assertFalse(update_sign.say(WriteFails(ValueError("closed")), "abc"))
        self.assertFalse(update_sign.say(WriteFails(UnicodeEncodeError("ascii", "x", 0, 1, "bad")), "abc"), "두 번 다 못 쓰면 거짓")


class EntryTest(unittest.TestCase):
    """재작업 1(Q 의 R2) — 명령줄 진입(`entry`)은 결과 코드를 돌려주기 전에 표준 출력을 한 번 비우고, 닫힌 파이프라서 비우기가 실패하면 표준 출력을 빈 장치로 돌려
    끝날 때 파이썬이 다시 비우다 실패해 종료 코드를 120 으로 바꾸는 일이 없게 한다."""

    class Dead:
        def __init__(self, fd):
            self.fd = fd

        def write(self, text):
            return len(text)

        def flush(self):
            raise BrokenPipeError(errno.EPIPE, "broken pipe")

        def fileno(self):
            return self.fd

    class NoDescriptor(Dead):
        def fileno(self):
            raise io.UnsupportedOperation("fileno")

    class Fine:
        def write(self, text):
            return len(text)

        def flush(self):
            return None

    def test_a_stdout_that_cannot_be_flushed_is_pointed_at_the_null_device_and_the_code_is_kept(self):
        with rts.temp_dir() as folder:
            fd = os.open(os.path.join(folder, "sink.bin"), os.O_WRONLY | os.O_CREAT | getattr(os, "O_BINARY", 0))
            calls = []
            try:
                with mock.patch.object(sys, "stdout", self.Dead(fd)), mock.patch.object(update_sign.os, "dup2", side_effect=lambda source, target: calls.append((source, target))):
                    self.assertEqual(update_sign.entry(lambda: 5), 5)
            finally:
                os.close(fd)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1], fd, "표준 출력의 파일 번호를 빈 장치로 돌린다")

    def test_a_stdout_that_cannot_be_flushed_and_has_no_descriptor_still_returns_the_code(self):
        with mock.patch.object(sys, "stdout", self.NoDescriptor(-1)):
            self.assertEqual(update_sign.entry(lambda: 7), 7)

    def test_a_healthy_stdout_is_left_alone(self):
        with mock.patch.object(sys, "stdout", self.Fine()), mock.patch.object(update_sign.os, "dup2") as dup:
            self.assertEqual(update_sign.entry(lambda: 0), 0)
        dup.assert_not_called()


def version_aware_run(verify_code, banner, *, version_code=0, version_error=None):
    """`openssl version` 에는 `banner` 로, 그 밖의(검증) 호출에는 `verify_code` 로 답하는 가짜 `subprocess.run`."""
    def reply(command):
        if command[1:2] == ["version"]:
            if version_error is not None:
                raise version_error
            return rts.FakeProcess(version_code, banner, b"")
        return rts.FakeProcess(verify_code, b"" if verify_code == 0 else b"Error: unknown option -rawin\n", b"")
    return rts.FakeRun(reply)


OLD_BANNER = b"OpenSSL 1.1.1q  5 Jul 2022\n"
NEW_BANNER = b"OpenSSL 3.0.13 30 Jan 2024 (Library: OpenSSL 3.0.13 30 Jan 2024)\n"
OLD_LINE = "자체 검증 2 · openssl 독립 확인: 건너뜀 — 찾은 openssl 이 OpenSSL 3.x 보다 낡았거나 다른 제품이라 독립 확인에 쓸 수 없다\n"


class OldOpensslTest(unittest.TestCase):
    """재작업 1(시험 렌즈 Q 의 R8) — PATH 의 openssl 이 3.x 보다 낡으면(`-rawin` 을 몰라 검증이 실패한다) '서명기나 키가 틀렸다' 고 오진하지 않고 '낡아서 쓸 수 없다' 고 정직하게 알린다.
    검증이 실패했을 때만 `openssl version` 을 한 번 더 부른다(성공 길의 호출은 하나 그대로). 버전을 못 읽으면 진짜 거절로 본다. `--require-openssl` 이면 이유가 다른 고정 문장으로 실패한다."""

    def flow(self, label, run, extra=()):
        seed = rts.canary_seed(label)
        with rts.temp_dir() as folder:
            path = manifest_file(folder, seed)
            got = run_tool(["--manifest", str(path), *extra], environ=environ_for(rts.seed_b64(seed)), which=fake_openssl, run=run, shipped=keys.Keyring())
            exists = (Path(folder) / "update-manifest.json.sig").exists()
        return got + (exists,)

    def test_an_old_openssl_is_reported_as_old_and_the_signature_is_still_made(self):
        run = version_aware_run(1, OLD_BANNER)
        code, out, err, exists = self.flow("old1", run)
        self.assertEqual((code, err, exists), (0, "", True))
        self.assertIn(OLD_LINE, out)
        self.assertNotIn("키가 틀렸다", out + err, "낡은 openssl 을 틀린 키로 오진하지 않는다")
        self.assertEqual(len(run.calls), 2)
        self.assertEqual(run.calls[1][0], ["openssl", "version"])

    def test_the_version_call_is_as_guarded_as_the_verify_call(self):
        run = version_aware_run(1, OLD_BANNER)
        self.flow("old2", run)
        (verify_command, verify_kwargs), (version_command, version_kwargs) = run.calls
        self.assertEqual(version_command, ["openssl", "version"])
        self.assertEqual(version_kwargs, verify_kwargs, "같은 환경(허용 목록)·같은 빈 임시 폴더·표준 입력 없음·같은 시간 한도")
        self.assertEqual(version_kwargs["timeout"], update_sign.OPENSSL_TIMEOUT)
        self.assertEqual(version_kwargs["stdin"], subprocess.DEVNULL)
        self.assertNotIn("UPDATE_SIGNING_KEY", version_kwargs["env"])
        self.assertEqual(version_kwargs["cwd"], os.path.dirname(verify_command[verify_command.index("-inkey") + 1]))

    def test_with_require_openssl_an_old_openssl_fails_with_its_own_sentence_and_no_signature(self):
        code, out, err, exists = self.flow("old3", version_aware_run(1, OLD_BANNER), extra=("--require-openssl",))
        self.assertEqual((code, out, exists), (1, "", False))
        self.assertEqual(err, "서명하지 않았다: 찾은 openssl 이 OpenSSL 3.x 보다 낡았거나 다른 제품이라 독립 확인을 할 수 없다(--require-openssl).\n")
        self.assertNotIn("키가 틀렸다", err)
        self.assertNotIn("찾지 못해", err, "못 찾은 것(건너뜀)과 낡은 것은 다른 문장이다")

    def test_a_modern_openssl_that_rejects_the_signature_is_still_a_real_rejection(self):
        for extra in ((), ("--require-openssl",)):
            with self.subTest(extra=extra):
                run = version_aware_run(1, NEW_BANNER)
                code, out, err, exists = self.flow("old4", run, extra=extra)
                self.assertEqual((code, out, exists), (1, "", False))
                self.assertEqual(err, "서명하지 않았다: openssl 독립 확인이 이 서명을 받지 않는다 — 서명기나 키가 틀렸다.\n")

    def test_the_banner_decides_old_modern_or_other_product(self):
        public, message, signature = pub_of("old5"), b"m", b"s" * 64
        table = {b"OpenSSL 1.1.1q  5 Jul 2022\n": update_sign.OPENSSL_OLD, b"OpenSSL 1.0.2k-fips  26 Jan 2017\n": update_sign.OPENSSL_OLD, b"OpenSSL 0.9.8zh 14 Jan 2016\n": update_sign.OPENSSL_OLD,
                 b"OpenSSL 2.9.9\n": update_sign.OPENSSL_OLD, b"LibreSSL 3.3.6\n": update_sign.OPENSSL_OLD, b"": update_sign.OPENSSL_OLD, b"not a banner\n": update_sign.OPENSSL_OLD,
                 b"OpenSSL 3.0.0\n": update_sign.OPENSSL_FAILED, b"OpenSSL 3.5.7 9 Jun 2026 (Library: OpenSSL 3.5.7 9 Jun 2026)\n": update_sign.OPENSSL_FAILED, b"OpenSSL 10.0.1\n": update_sign.OPENSSL_FAILED,
                 b"  OpenSSL 3.2.1\n": update_sign.OPENSSL_FAILED}
        for banner, expected in table.items():
            with self.subTest(banner=banner):
                self.assertEqual(update_sign.openssl_verify(public, message, signature, which=fake_openssl, run=version_aware_run(1, banner)), expected)

    def test_when_the_version_cannot_be_read_the_failure_is_a_real_rejection(self):
        public, message, signature = pub_of("old6"), b"m", b"s" * 64
        cases = {"version fails": version_aware_run(1, OLD_BANNER, version_code=1), "version cannot start": version_aware_run(1, OLD_BANNER, version_error=OSError("x")),
                 "version hangs": version_aware_run(1, OLD_BANNER, version_error=subprocess.TimeoutExpired("openssl", 60))}
        for label, run in cases.items():
            with self.subTest(case=label):
                self.assertEqual(update_sign.openssl_verify(public, message, signature, which=fake_openssl, run=run), update_sign.OPENSSL_FAILED)

    def test_a_successful_verification_never_asks_for_the_version(self):
        run = version_aware_run(0, OLD_BANNER)
        self.assertEqual(update_sign.openssl_verify(pub_of("old7"), b"m", b"s" * 64, which=fake_openssl, run=run), update_sign.OPENSSL_OK)
        self.assertEqual(len(run.calls), 1)


class GapClosingTest(unittest.TestCase):
    """재작업 1(시험 렌즈 Q 의 R5) — Q 의 변이 시험이 찾은 서명 도구의 시험 틈 넷(QS13·QS15·QS20·QS26)을 닫는다. 이 시험들은 Q 의 프로브 시험을 이 갈래의 이름·규칙에 맞게 옮긴 것이다."""

    def test_a_pem_with_a_good_header_and_body_but_a_wrong_footer_is_refused(self):
        """QS13 — 머리 줄·본문이 맞고 꼬리 줄만 틀린 PEM 은 거절한다(꼬리 줄 확인을 지워도 통과하던 틈)."""
        seed = rts.canary_seed("gap-pem")
        pem = rts.seed_pem(seed)
        end = "-----END " + rts.PEM_WORD + "-----"
        for label, wrong in {"another word": pem.replace(end, "-----FIN " + rts.PEM_WORD + "-----"), "footer of another key type": pem.replace(end, "-----END " + "PUBLIC KEY" + "-----"),
                             "footer with a trailing word": pem.replace(end, end + " x")}.items():
            with self.subTest(case=label):
                self.assertNotEqual(wrong, pem)
                with self.assertRaises(update_sign.SigningKeyError):
                    update_sign.parse_signing_key(wrong)
        update_sign.parse_signing_key(pem)

    def test_the_openssl_verify_call_carries_the_module_timeout(self):
        """QS15 — `openssl` 이 멈추면 서명 잡이 한도 없이 멈추지 않는다: 호출에 `OPENSSL_TIMEOUT` 이 실려 간다(사전 점검의 `GH_TIMEOUT` 단언과 같은 모양)."""
        seed = rts.canary_seed("gap-timeout")
        run = rts.FakeRun(rts.ok_process)
        with rts.temp_dir() as folder:
            path = manifest_file(folder, seed)
            code, _out, err = run_tool(["--manifest", str(path)], environ=environ_for(rts.seed_b64(seed)), which=fake_openssl, run=run, shipped=keys.Keyring())
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(run.calls[0][1].get("timeout"), update_sign.OPENSSL_TIMEOUT)
        self.assertTrue(0 < update_sign.OPENSSL_TIMEOUT <= 600)

    def test_a_failed_replace_with_overwrite_leaves_neither_a_temp_file_nor_a_changed_signature(self):
        """QS20 — `--overwrite` 는 같은 폴더의 임시 파일을 거쳐 바꿔 넣는다: 바꿔 넣기가 실패하면 `.sig-` 임시 파일을 지우고 옛 서명 파일을 그대로 둔다."""
        seed = rts.canary_seed("gap-replace")
        with rts.temp_dir() as folder:
            path = manifest_file(folder, seed)
            sig = Path(folder) / "update-manifest.json.sig"
            sig.write_bytes(b"old signature file\n")
            before = sorted(item.name for item in Path(folder).iterdir())
            with mock.patch.object(update_sign.os, "replace", side_effect=OSError("denied")):
                code, out, err = run_tool(["--manifest", str(path), "--overwrite"], environ=environ_for(rts.seed_b64(seed)), which=no_openssl, shipped=keys.Keyring())
            self.assertEqual((code, out), (1, ""))
            self.assertEqual(err, "예상하지 못한 오류로 멈췄다(종류: OSError). 서명 파일을 만들지 않았다.\n")
            self.assertEqual(sorted(item.name for item in Path(folder).iterdir()), before, "임시 파일을 남기지 않는다")
            self.assertEqual(sig.read_bytes(), b"old signature file\n", "옛 서명 파일은 그대로다")

    def test_a_manifest_one_byte_over_the_limit_is_refused_as_too_big_not_cut_and_signed(self):
        """QS26 — 상한보다 한 바이트 더 읽어야 큰 파일이 `size` 로 거절된다(상한만큼만 읽으면 잘린 바이트에 서명할 수 있다)."""
        seed = rts.canary_seed("gap-size")
        good = rts.manifest_bytes(seed)
        over = good[:-1] + b" " * (manifest.MAX_MANIFEST_BYTES - len(good) + 1) + b"\n"
        self.assertEqual(len(over), manifest.MAX_MANIFEST_BYTES + 1)
        with rts.temp_dir() as folder:
            path = Path(folder) / "update-manifest.json"
            path.write_bytes(over)
            code, out, err = run_tool(["--manifest", str(path)], environ=environ_for(rts.seed_b64(seed)), which=no_openssl, shipped=keys.Keyring())
            self.assertEqual((code, out), (4, ""))
            self.assertIn("(이유 이름표: size)", err)
            self.assertFalse((Path(folder) / "update-manifest.json.sig").exists())
        exact = good[:-1] + b" " * (manifest.MAX_MANIFEST_BYTES - len(good)) + b"\n"
        self.assertEqual(len(exact), manifest.MAX_MANIFEST_BYTES)
        with rts.temp_dir() as folder:
            path = Path(folder) / "update-manifest.json"
            path.write_bytes(exact)
            code, _out, err = run_tool(["--manifest", str(path)], environ=environ_for(rts.seed_b64(seed)), which=no_openssl, shipped=keys.Keyring())
            self.assertEqual(code, 0, err)


class ExclusiveSignatureFileTest(unittest.TestCase):
    """재작업 1(참고 N-1) — 서명 파일은 덮어쓰기를 요청하지 않으면 **배타적으로**(`O_EXCL`) 만든다: 검사와 쓰기 사이에 파일이 생겨도 덮어쓰지 않고, 쓰다 실패하면 반쯤 쓴 파일을 남기지 않는다."""

    def test_a_file_that_appears_after_the_check_is_never_overwritten(self):
        seed = rts.canary_seed("excl1")
        with rts.temp_dir() as folder:
            path = manifest_file(folder, seed)
            sig = Path(folder) / "update-manifest.json.sig"
            sig.write_bytes(b"written first by someone else\n")
            with mock.patch("os.path.exists", return_value=False):                 # 검사가 지나간 것처럼 — 그 사이에 파일이 생긴 경쟁
                code, out, err = run_tool(["--manifest", str(path)], environ=environ_for(rts.seed_b64(seed)), which=no_openssl)
            self.assertEqual((code, out), (2, ""))
            self.assertEqual(err, "서명 파일이 이미 있어 쓰지 않았다(덮어쓰려면 --overwrite).\n")
            self.assertEqual(sig.read_bytes(), b"written first by someone else\n")
            self.assertEqual(sorted(item.name for item in Path(folder).iterdir()), ["update-manifest.json", "update-manifest.json.sig"], "임시 파일을 남기지 않는다")

    def test_an_existing_signature_file_is_refused_first_before_the_key_or_the_manifest_is_even_looked_at(self):
        """`O_EXCL` 가 마지막 방어이고, 앞선 존재 검사는 일을 시작하기 전에 거절한다(키를 읽지도 서명하지도 openssl 을 부르지도 않는다)."""
        seed = rts.canary_seed("excl4")
        with rts.temp_dir() as folder:
            path = manifest_file(folder, seed)
            sig = Path(folder) / "update-manifest.json.sig"
            sig.write_bytes(b"already here\n")
            run = rts.FakeRun(rts.ok_process)
            for label, environ in {"no key at all": {}, "a malformed key": environ_for("not a key"), "a good key": environ_for(rts.seed_b64(seed))}.items():
                with self.subTest(case=label):
                    code, out, err = run_tool(["--manifest", str(path)], environ=environ, which=fake_openssl, run=run)
                    self.assertEqual((code, out, err), (2, "", "서명 파일이 이미 있어 쓰지 않았다(덮어쓰려면 --overwrite).\n"))
            self.assertEqual(run.calls, [], "openssl 을 부르지도 않는다")
            self.assertEqual(sig.read_bytes(), b"already here\n")

    def test_a_failed_write_leaves_no_half_written_signature_file(self):
        seed = rts.canary_seed("excl2")
        with rts.temp_dir() as folder:
            path = manifest_file(folder, seed)
            with mock.patch("os.fsync", side_effect=OSError("disk full")):
                code, out, err = run_tool(["--manifest", str(path)], environ=environ_for(rts.seed_b64(seed)), which=no_openssl)
            self.assertEqual((code, out), (1, ""))
            self.assertEqual(err, "예상하지 못한 오류로 멈췄다(종류: OSError). 서명 파일을 만들지 않았다.\n")
            self.assertEqual(sorted(item.name for item in Path(folder).iterdir()), ["update-manifest.json"])

    def test_overwrite_still_replaces_an_existing_signature_file(self):
        seed = rts.canary_seed("excl3")
        with rts.temp_dir() as folder:
            path = manifest_file(folder, seed)
            sig = Path(folder) / "update-manifest.json.sig"
            sig.write_bytes(b"old\n")
            code, _out, err = run_tool(["--manifest", str(path), "--overwrite"], environ=environ_for(rts.seed_b64(seed)), which=no_openssl)
            self.assertEqual((code, err), (0, ""))
            self.assertEqual(sig.read_bytes(), us.signature_file(seed, path.read_bytes()))
            self.assertEqual(sorted(item.name for item in Path(folder).iterdir()), ["update-manifest.json", "update-manifest.json.sig"])


class SelfCheckTest(unittest.TestCase):
    def run_flow(self, label, *, extra=(), which=no_openssl, run=None, shipped=None, signer=None):
        seed = rts.canary_seed(label)
        with rts.temp_dir() as folder:
            path = manifest_file(folder, seed)
            kwargs = {}
            if shipped is not None:
                kwargs["shipped"] = shipped
            if signer is not None:
                kwargs["signer"] = signer
            if run is not None:
                kwargs["run"] = run
            got = run_tool(["--manifest", str(path), *extra], environ=environ_for(rts.seed_b64(seed)), which=which, **kwargs)
            exists = (Path(folder) / "update-manifest.json.sig").exists()
        return got + (exists,)

    def test_an_empty_shipped_list_warns_with_the_fixed_sentence_and_the_flag_makes_it_a_failure(self):
        code, out, err, exists = self.run_flow("sc1", shipped=keys.Keyring())
        self.assertEqual((code, exists), (0, True))
        self.assertIn("경고 — 내장된 공개키 목록이 비어 있어 지금의 앱은 이 서명을 아직 받지 않는다", out)
        code, out, err, exists = self.run_flow("sc1", shipped=keys.Keyring(), extra=("--require-shipped-key",))
        self.assertEqual((code, exists), (1, False))
        self.assertEqual(err, "서명하지 않았다: 앱에 내장된 공개키 목록이 이 서명을 받지 않는다(--require-shipped-key).\n")

    def test_the_real_shipped_list_of_this_tree_is_checked_by_default(self):
        """기본 값은 앱 소스의 `shipped_keyring()` — 지금은 비어 있어 경고다(키를 넣는 T3 변경 뒤에는 이 시험이 알려 준다)."""
        code, out, _err, _exists = self.run_flow("sc2")
        self.assertEqual(code, 0)
        self.assertEqual(len(keys.shipped_keyring()), len(keys.SHIPPED_KEYS))
        if not keys.SHIPPED_KEYS:
            self.assertIn("경고 — 내장된 공개키 목록이 비어 있어", out)
        self.assertIn("자체 검증 1 · 앱에 내장된 공개키 목록: ", out)

    def test_a_shipped_list_holding_this_key_passes_silently_and_with_the_flag(self):
        ring = keys.Keyring([(keys.ROLE_CURRENT, pub_of("sc3"))])
        for extra in ((), ("--require-shipped-key",)):
            code, out, err, exists = self.run_flow("sc3", shipped=ring, extra=extra)
            self.assertEqual((code, exists), (0, True), err)
            self.assertIn("자체 검증 1 · 앱에 내장된 공개키 목록: 통과\n", out)
            self.assertNotIn("경고", out)

    def test_a_shipped_list_with_only_another_key_warns_that_this_key_is_missing(self):
        ring = keys.Keyring([(keys.ROLE_CURRENT, pub_of("sc4-other"))])
        code, out, err, exists = self.run_flow("sc4", shipped=ring)
        self.assertEqual((code, exists), (0, True))
        self.assertIn("경고 — 내장된 공개키 목록에 이 키가 없어 지금의 앱은 이 서명을 아직 받지 않는다", out)
        code, _out, _err, exists = self.run_flow("sc4", shipped=ring, extra=("--require-shipped-key",))
        self.assertEqual((code, exists), (1, False))

    def test_a_revoked_key_is_not_accepted_by_the_app_so_it_warns_and_the_flag_fails(self):
        public = pub_of("sc5")
        ring = keys.Keyring([(keys.ROLE_CURRENT, public)], revoked=[rts.key_id(public)])
        code, out, _err, exists = self.run_flow("sc5", shipped=ring)
        self.assertEqual((code, exists), (0, True))
        self.assertIn("경고 — 내장된 공개키 목록에서 폐기된 키라 지금의 앱은 이 서명을 받지 않는다", out)
        code, _out, _err, exists = self.run_flow("sc5", shipped=ring, extra=("--require-shipped-key",))
        self.assertEqual((code, exists), (1, False))

    def test_a_shipped_list_that_maps_this_key_name_to_another_key_is_a_hard_failure_even_without_the_flag(self):
        wrong = pub_of("sc3-wrong")

        class LyingRing(keys.Keyring):
            def lookup(self, key_id):
                return wrong
        code, out, err, exists = self.run_flow("sc3", shipped=LyingRing([(keys.ROLE_CURRENT, wrong)]))
        self.assertEqual((code, out, exists), (1, "", False))
        self.assertEqual(err, "서명하지 않았다: 앱에 내장된 공개키로 확인하면 서명이 맞지 않는다 — 내장 키와 서명 키가 다르다.\n")

    def test_a_signer_that_makes_a_wrong_signature_is_caught_by_the_apps_verifier(self):
        for name, signer in {"junk": lambda s, m: b"\x01" * 64, "short": lambda s, m: b"\x01" * 63, "other message": lambda s, m: update_sign.sign(s, m + b" ")}.items():
            with self.subTest(signer=name):
                code, out, err, exists = self.run_flow("sc6", signer=signer)
                self.assertEqual((code, out, exists), (1, "", False))
                self.assertEqual(err, "서명하지 않았다: 앱과 같은 검증기가 방금 만든 서명을 받지 않는다 — 서명기나 키가 틀렸다.\n")

    def test_openssl_missing_is_skipped_with_a_reason_and_the_flag_makes_it_a_failure(self):
        code, out, err, exists = self.run_flow("sc7", which=no_openssl)
        self.assertEqual((code, exists), (0, True))
        self.assertIn("자체 검증 2 · openssl 독립 확인: 건너뜀 — openssl 을 찾지 못했다\n", out)
        code, out, err, exists = self.run_flow("sc7", which=no_openssl, extra=("--require-openssl",))
        self.assertEqual((code, exists), (1, False))
        self.assertEqual(err, "서명하지 않았다: openssl 을 찾지 못해 독립 확인을 할 수 없다(--require-openssl).\n")

    def test_openssl_that_does_not_confirm_stops_the_run_and_leaves_no_signature(self):
        for name, reply in {"failure": rts.failing_process, "usage error": lambda command: rts.FakeProcess(2, b"", b"usage"), "killed": lambda command: rts.FakeProcess(-9, b"", b"")}.items():
            run = rts.FakeRun(reply)
            code, out, err, exists = self.run_flow("sc8", which=fake_openssl, run=run)
            with self.subTest(name=name):
                self.assertEqual((code, out, exists), (1, "", False))
                self.assertEqual(err, "서명하지 않았다: openssl 독립 확인이 이 서명을 받지 않는다 — 서명기나 키가 틀렸다.\n")

    def test_openssl_that_cannot_be_started_or_hangs_is_a_failure_not_a_skip(self):
        for name, error in {"os error": OSError("x"), "timeout": subprocess.TimeoutExpired("openssl", 60)}.items():
            def broken(command, **kwargs):
                raise error
            code, out, err, exists = self.run_flow("sc8", which=fake_openssl, run=broken)
            with self.subTest(name=name):
                self.assertEqual((code, out, exists), (1, "", False))
                self.assertEqual(err, "서명하지 않았다: openssl 독립 확인이 이 서명을 받지 않는다 — 서명기나 키가 틀렸다.\n")

    def test_the_openssl_call_is_a_fixed_argument_list_over_public_files_only(self):
        seed = rts.canary_seed("sc9")
        public = pub_of("sc9")
        run = rts.FakeRun(rts.ok_process)
        with rts.temp_dir() as folder:
            path = manifest_file(folder, seed)
            data = path.read_bytes()
            code, _out, _err = run_tool(["--manifest", str(path)], environ=environ_for(rts.seed_b64(seed)), which=fake_openssl, run=run)
            signature = base64.b64decode((Path(folder) / "update-manifest.json.sig").read_bytes().strip())
        self.assertEqual(code, 0)
        command, kwargs = run.calls[0]
        self.assertEqual(command[0], "openssl")
        self.assertEqual(len(command), 13)
        self.assertEqual([command[index] for index in (1, 2, 3, 4, 6, 7, 8, 9, 11)], ["pkeyutl", "-verify", "-pubin", "-inkey", "-keyform", "DER", "-rawin", "-in", "-sigfile"])
        self.assertNotIn("shell", kwargs)
        self.assertIsInstance(command, list)
        self.assertIn(bytes.fromhex("302a300506032b6570032100") + public, run.file_texts, "공개키(SPKI DER)")
        self.assertIn(manifest.SIGN_PREFIX + data, run.file_texts, "서명 대상 바이트(접두어 + 매니페스트)")
        self.assertIn(signature, run.file_texts, "서명 64바이트")
        self.assertEqual(len(run.file_texts), 3)


class OpensslChildEnvironmentTest(unittest.TestCase):
    """재작업 1(S-1) — `openssl` 하위 프로세스는 서명 키 변수(와 다른 비밀)를 물려받지 않는다: 허용 목록의 변수만, 빈 임시 폴더에서, 표준 입력 없이."""

    SECRETS = {"GITHUB_TOKEN": "CANARY_TOKEN_VALUE_1", "GH_TOKEN": "CANARY_TOKEN_VALUE_2", "AWS_SECRET_ACCESS_KEY": "CANARY_TOKEN_VALUE_3", "MY_PASSWORD": "CANARY_TOKEN_VALUE_4",
               "ACTIONS_RUNTIME_TOKEN": "CANARY_TOKEN_VALUE_5", "NPM_TOKEN": "CANARY_TOKEN_VALUE_6", "SIGNING_NOTE": "CANARY_TOKEN_VALUE_7"}

    def test_the_child_gets_only_allowlisted_variables_and_never_the_key_or_any_secret_looking_one(self):
        seed = rts.canary_seed("env1")
        environ = {"PATH": "/opt/bin", "SystemRoot": "C:/Windows", "TEMP": "/tmp/x", "LANG": "C", "OPENSSL_CONF": "/etc/ssl/openssl.cnf", "UPDATE_SIGNING_KEY": rts.seed_b64(seed),
                   "UPDATE_OTHER": "other-value", "ALL_PROXY": "proxy.example.invalid", "HOME": "/home/someone", **self.SECRETS}
        with rts.temp_dir() as folder:
            path = manifest_file(folder, seed)
            run = rts.FakeRun(rts.ok_process)
            code, out, err = run_tool(["--manifest", str(path)], environ=environ, which=fake_openssl, run=run, shipped=keys.Keyring())
        self.assertEqual((code, err), (0, ""), out)
        self.assertEqual(len(run.calls), 1)
        _command, kwargs = run.calls[0]
        self.assertIn("env", kwargs, "하위 프로세스에 환경을 직접 정해 넘긴다(넘기지 않으면 부모의 환경 전부를 물려받는다)")
        child = kwargs["env"]
        self.assertEqual(sorted(name.upper() for name in child), ["LANG", "OPENSSL_CONF", "PATH", "SYSTEMROOT", "TEMP"])
        self.assertEqual((child["PATH"], child["SystemRoot"], child["TEMP"]), ("/opt/bin", "C:/Windows", "/tmp/x"), "허용한 변수의 값은 그대로 간다")
        shown = repr(kwargs)
        rts.assert_no_leak(self, seed, shown)
        for secret in self.SECRETS.values():
            self.assertNotIn(secret, shown)
        for name in ("UPDATE_SIGNING_KEY", "UPDATE_OTHER", "HOME", "ALL_PROXY"):
            self.assertNotIn(name, child)

    def test_the_allowlist_has_no_secret_looking_name_and_never_the_key_variable(self):
        allowed = update_sign.CHILD_ENV_ALLOWED
        self.assertNotIn(update_sign.ENV_NAME, allowed)
        self.assertTrue(allowed, "빈 허용 목록이면 진짜 openssl 이 못 돈다")
        for name in allowed:
            self.assertEqual(name, name.upper(), "허용 목록은 대문자로 적는다(이름 비교는 대소문자를 가리지 않는다)")
            for fragment in ("KEY", "TOKEN", "SECRET", "PASS", "CRED", "AUTH", "SIGN", "PRIVATE"):
                self.assertNotIn(fragment, name, f"{name} 은 비밀처럼 보이는 이름이다")
        self.assertEqual(update_sign.child_environment({}), {})
        got = update_sign.child_environment({"path": "x", "UPDATE_SIGNING_KEY": "y", "Temp": "z", "GITHUB_TOKEN": "t", 5: "n", "LANG": 7})
        self.assertEqual(got, {"path": "x", "Temp": "z"}, "이름의 대소문자는 가리지 않고 값이 글이 아닌 것·이름이 글이 아닌 것은 버린다")

    def test_a_real_child_process_never_sees_the_key_or_other_secrets_and_runs_in_the_public_folder(self):
        seed = rts.canary_seed("env2")
        passthrough = {key: value for key, value in os.environ.items() if key.upper() in ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "TMPDIR")}
        runtime_only = {key: value for key, value in os.environ.items() if key.upper() in ("LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH")}      # 파이썬 자신이 뜨는 데 필요한 것 — 시험의 가짜 하위 프로그램이 파이썬이라서 시험 쪽이 더해 준다
        environ = {**passthrough, "UPDATE_SIGNING_KEY": rts.seed_b64(seed), **self.SECRETS}
        passed_by_the_tool = []
        with rts.temp_dir() as folder:
            record, fake = Path(folder) / "record.json", Path(folder) / "fake_child.py"
            fake.write_text("import json, os, sys\nwith open(%r, 'w', encoding='utf-8') as handle:\n"
                            "    json.dump({'env': dict(os.environ), 'cwd': os.getcwd(), 'args': sys.argv[1:], 'files': sorted(os.listdir('.'))}, handle)\n" % str(record), encoding="utf-8")

            def run_real(command, **kwargs):
                passed_by_the_tool.append(dict(kwargs["env"]))                       # 도구가 넘긴 환경 그대로
                merged = dict(kwargs["env"])
                merged.update(runtime_only)
                return subprocess.run([sys.executable, str(fake), *command[1:]], **dict(kwargs, env=merged))
            path = manifest_file(folder, seed)
            code, out, err = run_tool(["--manifest", str(path)], environ=environ, which=fake_openssl, run=run_real, shipped=keys.Keyring())
            self.assertEqual((code, err), (0, ""), out)
            info = json.loads(record.read_text(encoding="utf-8"))
        rts.assert_no_leak(self, seed, json.dumps(info), json.dumps(passed_by_the_tool))
        allowed = set(update_sign.CHILD_ENV_ALLOWED)
        for label, names in (("도구가 넘긴 환경", {name.upper() for name in passed_by_the_tool[0]}), ("진짜 하위 프로세스가 본 환경", {name.upper() for name in info["env"]} - {name.upper() for name in runtime_only})):
            self.assertTrue(names <= allowed, f"{label}: 허용 목록 밖의 변수 {sorted(names - allowed)}")
            self.assertFalse(names & {"UPDATE_SIGNING_KEY", *self.SECRETS}, f"{label}에 비밀이 있다")
        for key, value in passthrough.items():
            if key.upper() in update_sign.CHILD_ENV_ALLOWED:
                self.assertEqual(info["env"].get(key, info["env"].get(key.upper())), value, f"허용한 변수 {key} 는 진짜 하위 프로세스에도 간다")
        self.assertEqual(info["files"], ["message.bin", "public.der", "signature.bin"], "하위 프로세스의 현재 폴더에는 공개 파일 셋뿐이다")
        self.assertEqual(os.path.normcase(os.path.realpath(info["cwd"])), os.path.normcase(os.path.realpath(os.path.dirname(info["args"][info["args"].index("-inkey") + 1]))))

    def test_the_child_runs_in_the_folder_that_holds_only_the_three_public_files_and_has_no_standard_input(self):
        seed = rts.canary_seed("env3")
        run = rts.FakeRun(rts.ok_process)
        with rts.temp_dir() as folder:
            path = manifest_file(folder, seed)
            code, _out, err = run_tool(["--manifest", str(path)], environ=environ_for(rts.seed_b64(seed)), which=fake_openssl, run=run, shipped=keys.Keyring())
        self.assertEqual((code, err), (0, ""))
        command, kwargs = run.calls[0]
        public_folder = os.path.dirname(command[command.index("-inkey") + 1])
        self.assertEqual(kwargs.get("cwd"), public_folder, "하위 프로세스는 공개 파일만 든 임시 폴더에서 돈다(프로젝트 폴더나 운영자의 현재 폴더에서 아무것도 줍지 못한다)")
        self.assertEqual(kwargs.get("stdin"), subprocess.DEVNULL)
        self.assertEqual(len(run.file_texts), 3)

    def test_a_liar_openssl_that_always_says_yes_cannot_rescue_a_signature_the_app_refuses(self):
        seed = rts.canary_seed("liar")
        run = rts.FakeRun(rts.ok_process)
        with rts.temp_dir() as folder:
            path = manifest_file(folder, seed)
            code, out, err = run_tool(["--manifest", str(path)], environ=environ_for(rts.seed_b64(seed)), which=fake_openssl, run=run, signer=lambda s, m: b"\x01" * 64, shipped=keys.Keyring())
            exists = (Path(folder) / "update-manifest.json.sig").exists()
        self.assertEqual((code, out, exists), (1, "", False))
        self.assertEqual(err, "서명하지 않았다: 앱과 같은 검증기가 방금 만든 서명을 받지 않는다 — 서명기나 키가 틀렸다.\n")
        self.assertEqual(run.calls, [], "앱의 검증기가 먼저 거절하므로 openssl 은 부르지도 않는다")


class OpensslLookupTest(unittest.TestCase):
    """재작업 1(S-1) — `openssl` 실행 파일은 `PATH` 의 **절대 경로 항목**에서만 찾는다: 현재 폴더·빈 항목·상대 경로 항목은 보지 않고, 윈도에서는 `openssl.exe` 만 쓴다."""

    NAME = "openssl.exe" if os.name == "nt" else "openssl"

    def tool(self, folder, name=None):
        path = Path(folder) / (name or self.NAME)
        path.write_bytes(b"not a real program")
        os.chmod(path, 0o755)
        return str(path)

    def test_the_first_absolute_entry_that_holds_the_program_wins_and_empty_or_relative_entries_are_skipped(self):
        with rts.temp_dir() as first, rts.temp_dir() as second:
            path_text = os.pathsep.join(["", ".", "relative_dir", first, second])
            self.assertIsNone(update_sign.find_openssl({"PATH": path_text}))
            wanted = self.tool(second)
            self.assertEqual(update_sign.find_openssl({"PATH": path_text}), wanted)
            earlier = self.tool(first)
            self.assertEqual(update_sign.find_openssl({"PATH": path_text}), earlier, "앞선 항목이 이긴다")

    def test_the_current_folder_is_never_searched_whatever_the_path_text_is(self):
        with rts.temp_dir() as here, rts.temp_dir() as bare:
            self.tool(here)
            before = os.getcwd()
            os.chdir(here)
            try:
                for path_text in ("", ".", os.pathsep.join(["", "."]), os.pathsep.join(["relative", ""]), "bin", os.curdir + os.sep, bare):
                    with self.subTest(path=path_text):
                        self.assertIsNone(update_sign.find_openssl({"PATH": path_text}))
                self.assertIsNone(update_sign.find_openssl({}), "PATH 가 없으면 못 찾은 것이다(현재 폴더로 돌아가지 않는다)")
                self.assertIsNone(update_sign.find_openssl({"PATH": 5}))
            finally:
                os.chdir(before)

    def test_on_windows_only_exe_files_run_and_batch_files_are_never_used(self):
        with rts.temp_dir() as folder:
            for name in ("openssl.cmd", "openssl.bat", "openssl.com", "openssl", "OPENSSL.TXT"):
                self.tool(folder, name)
            self.assertIsNone(update_sign.find_openssl({"PATH": folder}, windows=True))
            wanted = self.tool(folder, "openssl.exe")
            self.assertEqual(update_sign.find_openssl({"PATH": folder}, windows=True), wanted)

    def test_the_variable_name_is_found_in_any_case_and_quoted_windows_entries_work(self):
        with rts.temp_dir() as folder:
            wanted = self.tool(folder)
            for key in ("PATH", "Path", "path"):
                self.assertEqual(update_sign.find_openssl({key: folder}), wanted, key)
            wanted_exe = self.tool(folder, "openssl.exe")
            self.assertEqual(update_sign.find_openssl({"Path": '"' + folder + '"'}, windows=True), wanted_exe)

    @unittest.skipIf(os.name == "nt", "윈도에는 실행 권한 비트가 없다")
    def test_a_file_without_the_execute_permission_is_not_a_program_on_posix(self):
        with rts.temp_dir() as folder:
            path = Path(self.tool(folder))
            os.chmod(path, 0o644)
            self.assertIsNone(update_sign.find_openssl({"PATH": folder}))
            os.chmod(path, 0o755)
            self.assertEqual(update_sign.find_openssl({"PATH": folder}), str(path))

    def test_the_default_lookup_of_the_tool_is_this_one_not_the_shells(self):
        """`which` 를 안 주면 이 찾기를 쓴다 — 도구가 PATH 와 환경에서 찾은 값이 `find_openssl(환경)` 과 같다."""
        calls = []
        with rts.temp_dir() as folder:
            seed = rts.canary_seed("lookup")
            path = manifest_file(folder, seed)
            run = rts.FakeRun(rts.ok_process)
            program = self.tool(folder)
            environ = {"UPDATE_SIGNING_KEY": rts.seed_b64(seed), "PATH": folder}
            code, out, err = run_tool(["--manifest", str(path)], environ=environ, run=run, shipped=keys.Keyring())
            calls = list(run.calls)
        self.assertEqual((code, err), (0, ""), out)
        self.assertEqual(calls[0][0][0], program, "도구가 부른 실행 파일은 PATH 의 절대 경로 항목에서 찾은 것이다")
        self.assertIn("자체 검증 2 · openssl 독립 확인: 통과\n", out)


def openssl_major(exe):
    """진짜 `openssl version` 의 큰 번호 — 읽을 수 없으면 None."""
    try:
        done = subprocess.run([exe, "version"], capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    found = re.match(rb"OpenSSL ([0-9]+)[.]", done.stdout.lstrip()) if done.returncode == 0 else None
    return int(found.group(1)) if found else None


@unittest.skipUnless(sys.executable, "파이썬 실행 파일이 필요하다")
class EndToEndTest(unittest.TestCase):
    """진짜 파이썬 하위 프로세스로 스크립트를 돌린다 — 파일 하나로 서고(`src` 를 스스로 경로에 올린다) 진짜 `openssl` 이 있으면 독립 확인까지 통과한다."""

    def run_script(self, seed_text, path, *extra, io_encoding="utf-8", stdout=subprocess.PIPE):
        environ = {key: value for key, value in os.environ.items() if not key.startswith("UPDATE_")}
        environ.pop("PYTHONPATH", None)
        environ["PYTHONUTF8"] = "1"
        environ["PYTHONIOENCODING"] = io_encoding            # 부모 환경(예: cp949)에 흔들리지 않게 자식의 입출력 인코딩을 못박는다(Q 의 R3) — 일부러 다르게 줄 때만 바꾼다
        if seed_text is not None:
            environ["UPDATE_SIGNING_KEY"] = seed_text
        return subprocess.run([sys.executable, "-X", "utf8", str(SCRIPT), "--manifest", str(path), *extra], stdout=stdout, stderr=subprocess.PIPE, env=environ, timeout=300)

    def test_a_closed_output_pipe_keeps_the_signature_and_ends_with_code_5_and_the_ascii_sentence(self):
        """재작업 1(Q 의 R2) — 읽는 쪽이 이미 닫힌 파이프로 진짜 하위 프로세스를 돌린다: 서명 파일은 그대로 있고 종료 코드는 5(끝날 때 다시 비우다 120 으로 바뀌지 않는다)·표준 오류에는 ASCII 고정 문장뿐이다."""
        seed = rts.canary_seed("e2e-pipe")
        with rts.temp_dir() as folder:
            path = manifest_file(folder, seed)
            read_end, write_end = os.pipe()
            os.close(read_end)
            try:
                done = self.run_script(rts.seed_b64(seed), path, stdout=write_end)
            finally:
                os.close(write_end)
            text = done.stderr.decode("utf-8", "replace")
            self.assertEqual(done.returncode, 5, text)
            self.assertEqual((Path(folder) / "update-manifest.json.sig").read_bytes(), us.signature_file(seed, path.read_bytes()))
        self.assertIn(update_sign.MSG_OUTPUT_FAILED, text)
        for word in ("Traceback", "Exception ignored", "BrokenPipe"):
            self.assertNotIn(word, text)
        rts.assert_no_leak(self, seed, text)

    def test_the_script_signs_for_real_and_the_app_accepts_it(self):
        seed = rts.canary_seed("e2e")
        with rts.temp_dir() as folder:
            path = manifest_file(folder, seed)
            done = self.run_script(rts.seed_b64(seed), path)
            out, err = done.stdout.decode("utf-8").replace("\r\n", "\n"), done.stderr.decode("utf-8").replace("\r\n", "\n")
            self.assertEqual((done.returncode, err), (0, ""), out)
            rts.assert_no_leak(self, seed, out, err)
            signature = (Path(folder) / "update-manifest.json.sig").read_bytes()
            verified = manifest.read_and_verify(path.read_bytes(), signature, keyring=keys.Keyring([(keys.ROLE_CURRENT, pub_of("e2e"))]), channels=manifest.CHANNELS_OFFLINE)
            self.assertEqual(verified.version, "1.0.1")
        line = [item for item in out.split("\n") if item.startswith("자체 검증 2")]
        self.assertEqual(len(line), 1)
        self.assertIn(line[0], ("자체 검증 2 · openssl 독립 확인: 통과", "자체 검증 2 · openssl 독립 확인: 건너뜀 — openssl 을 찾지 못했다", OLD_LINE.rstrip(chr(10))),
                      "진짜 openssl 이 3.x 면 통과, 없으면 건너뜀, 낡았으면 낡았다고 건너뜀(어느 쪽이든 서명은 만들어졌다 — 낡은 openssl 을 틀린 키로 오진하지 않는다, Q 의 R8)")

    def test_the_result_is_not_shaken_by_the_parents_output_encoding(self):
        """재작업 1(Q 의 R3) — 부모 환경에 `PYTHONIOENCODING=cp949` 가 있어도 자식 환경은 시험이 못박아 같은 결과가 나온다."""
        seed = rts.canary_seed("e2e-enc")
        with mock.patch.dict(os.environ, {"PYTHONIOENCODING": "cp949", "PYTHONUTF8": "0"}):
            with rts.temp_dir() as folder:
                path = manifest_file(folder, seed)
                done = self.run_script(rts.seed_b64(seed), path)
                out = done.stdout.decode("utf-8").replace(chr(13) + chr(10), chr(10))
                self.assertEqual((done.returncode, done.stderr), (0, b""), out)
                self.assertTrue(out.startswith("서명했다: update-manifest.json.sig" + chr(10)), out)

    def test_a_console_that_cannot_write_the_sentences_does_not_turn_a_signature_into_a_failure(self):
        """재작업 1(Q 의 R2) — 출력 인코딩이 한글·긴 줄표를 못 써도(진짜 하위 프로세스) 서명은 정상이고 종료 0, 못 쓰는 글자만 물음표가 된다."""
        for encoding in ("ascii", "cp949"):
            with self.subTest(encoding=encoding):
                seed = rts.canary_seed("e2e-" + encoding)
                with rts.temp_dir() as folder:
                    path = manifest_file(folder, seed)
                    done = self.run_script(rts.seed_b64(seed), path, io_encoding=encoding)
                    signature = (Path(folder) / "update-manifest.json.sig")
                    self.assertEqual((done.returncode, done.stderr), (0, b""), done.stdout)
                    self.assertEqual(signature.read_bytes(), us.signature_file(seed, path.read_bytes()))
                text = done.stdout.decode(encoding)
                self.assertIn(rts.key_id(pub_of("e2e-" + encoding)), text)
                self.assertIn("?", text)
                rts.assert_no_leak(self, seed, text, done.stderr)

    def test_a_real_openssl_in_path_confirms_through_the_filtered_environment_and_the_empty_folder(self):
        """재작업 1(S-1) — 하위 프로세스에 허용 목록의 환경만 주고 빈 임시 폴더에서 돌려도 진짜 openssl 은 서명을 참으로 본다(없는 PC 에서는 건너뜀 확인)."""
        environ = {key: value for key, value in os.environ.items() if not key.startswith("UPDATE_")}
        found = update_sign.find_openssl(environ)
        if found is None:
            self.skipTest("PATH 의 절대 경로 항목에 openssl 이 없다 — 이 칸에서는 독립 확인이 건너뜀이다")
        if openssl_major(found) is None or openssl_major(found) < 3:
            self.skipTest("PATH 의 openssl 이 3.x 가 아니다 — 이 칸에서는 독립 확인이 '낡아서 건너뜀' 이다(위 시험이 그 문장을 본다)")
        seed = rts.canary_seed("e2e-real")
        with rts.temp_dir() as folder:
            path = manifest_file(folder, seed)
            done = self.run_script(rts.seed_b64(seed), path)
            out = done.stdout.decode("utf-8").replace("\r\n", "\n")
        self.assertEqual(done.returncode, 0, out)
        self.assertIn("자체 검증 2 · openssl 독립 확인: 통과\n", out)

    def test_the_real_tool_never_runs_a_fake_openssl_from_the_current_folder_or_a_batch_file_in_path(self):
        """재작업 1(S-1) — 현재 폴더의 가짜 openssl 과 PATH 의 `.cmd`·`.bat` 은 실행되지 않는다(실행됐다면 표시 파일이 생긴다). 키 값도 어디에도 안 나간다."""
        seed = rts.canary_seed("e2e-fake")
        with rts.temp_dir() as folder:
            base = Path(folder)
            path = manifest_file(base, seed)
            marker, here, on_path = base / "marker.txt", base / "here", base / "bin"
            here.mkdir()
            on_path.mkdir()
            if os.name == "nt":
                text, names = '@echo off\r\necho ran> "%s"\r\nexit /b 0\r\n' % marker, ("openssl.cmd", "openssl.bat")
            else:
                text, names = '#!/bin/sh\necho ran > "%s"\nexit 0\n' % marker, ("openssl",)
            for name in names:
                (here / name).write_bytes(text.encode("ascii"))
                os.chmod(here / name, 0o755)
                if os.name == "nt":
                    (on_path / name).write_bytes(text.encode("ascii"))
            environ = {key: value for key, value in os.environ.items() if not key.startswith("UPDATE_") and key.upper() != "PYTHONPATH"}
            environ["PYTHONUTF8"] = "1"
            environ["PYTHONIOENCODING"] = "utf-8"            # 부모 환경(예: cp949)에 흔들리지 않게 자식의 입출력 인코딩을 못박는다(Q 의 R3)
            environ["PATH"] = str(on_path)
            environ["UPDATE_SIGNING_KEY"] = rts.seed_b64(seed)
            done = subprocess.run([sys.executable, "-X", "utf8", str(SCRIPT), "--manifest", str(path)], capture_output=True, env=environ, cwd=str(here), timeout=300)
            out, err = done.stdout.decode("utf-8").replace("\r\n", "\n"), done.stderr.decode("utf-8").replace("\r\n", "\n")
            self.assertEqual((done.returncode, err), (0, ""), out)
            self.assertFalse(marker.exists(), "가짜 openssl 이 실행됐다 — 현재 폴더나 PATH 의 배치 파일을 믿었다")
            self.assertIn("자체 검증 2 · openssl 독립 확인: 건너뜀 — openssl 을 찾지 못했다\n", out)
            rts.assert_no_leak(self, seed, out, err)

    def test_the_script_without_the_variable_stops_without_a_traceback(self):
        seed = rts.canary_seed("e2e2")
        with rts.temp_dir() as folder:
            path = manifest_file(folder, seed)
            done = self.run_script(None, path)
        self.assertEqual(done.returncode, 3)
        self.assertNotIn(b"Traceback", done.stderr)
        self.assertEqual(done.stderr.decode("utf-8").replace("\r\n", "\n"), "서명하지 않았다: 환경 변수 UPDATE_SIGNING_KEY 가 없거나 비어 있다.\n")

    def test_a_real_run_with_a_bad_key_prints_nothing_of_it(self):
        seed = rts.canary_seed("e2e3")
        with rts.temp_dir() as folder:
            path = manifest_file(folder, seed)
            done = self.run_script(rts.seed_b64(seed) + "AA", path)
        self.assertEqual(done.returncode, 3)
        rts.assert_no_leak(self, seed, done.stdout, done.stderr)


if __name__ == "__main__":
    unittest.main()
