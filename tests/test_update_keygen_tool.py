"""`scripts/update_keygen.py`(서명 키 쌍 만들기, RELEASE 설계서 3-5·R-1, V1REL12) 시험 — 이 도구는 **시험에서만** 임시 폴더로 돌린다(진짜 키를 만들지 않는다).

지키는 것:
  1) 비밀 씨앗(32바이트 base64 한 줄 44글자 + LF)을 `--out` 파일에만 쓰고 화면에는 **공개키·지문(SHA-256 앞 16글자)만** 보인다 — 화면 글은 고정 문장과 공개 값뿐이라 정확히 같은 글이어야 한다(카나리 씨앗이 한 글자도 없다).
  2) 이미 있는 이름(파일·폴더)과 git 작업 폴더 안과 없는 폴더는 **거절**하고, 거절할 때는 난수를 뽑지도 파일을 만들지도 않는다.
  3) 파일은 배타적으로 만들어지고(덮어쓰기 0) 현재 사용자만 읽는 권한(POSIX)이며, 쓰기에 실패하면 반쯤 쓴 파일을 지운다. 만든 뒤 다시 읽어 같은 공개키가 나오는지 확인한다.
  4) `--spare` 는 예비 키 쌍의 표시일 뿐 같은 규칙이다. `--public-of` 는 이미 만든 파일의 공개키·지문만 보인다(두 곳의 사본이 같은지 비밀을 보이지 않고 견주는 방법).
  5) 만든 파일은 서명 도구가 읽어 서명하고 앱의 검증기가 받아들인다.
  6) 화면 경고는 셋이다 — 셋째는 윈도에서 `0o600` 이 접근 권한을 좁히지 않는다는 사실을 알린다(재작업 1·S-4, 정확 일치).
네트워크·실제 시크릿 없이 돈다(난수는 시험이 끼운 카나리 씨앗).
"""
import ast
import base64
import errno
import io
import os
import stat
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

import release_tools_support as rts
import update_support as us

from chanceblog_desktop.update import keys, manifest

import update_keygen
import update_sign

ROOT = rts.ROOT
SCRIPT = ROOT / "scripts" / "update_keygen.py"
run_tool = rts.Capture(update_keygen.main)

WARNING_LINES = ("[주의] 비밀 파일의 내용을 채팅·이슈·메일·메신저·클라우드 드라이브에 붙이지 않는다. 이 화면의 공개키와 지문만 [답변] 에 적는다.\n"
                 "[주의] 비밀 파일은 저장소·클라우드 동기화 폴더 밖의 서로 다른 오프라인 곳 두 군데에 복사하고, --public-of 로 두 곳의 지문이 같은지 확인한다.\n"
                 "[주의] 윈도에서는 파일 권한 비트(0o600)가 접근 권한을 좁히지 않는다 — 비밀 파일은 본인 계정만 읽는 폴더(사용자 프로필 아래)에 두고, 여러 사람이 쓰는 PC 라면 폴더 권한을 따로 확인한다(icacls).\n")


def entropy_of(seed):
    calls = []

    def entropy(count):
        calls.append(count)
        return seed
    entropy.calls = calls
    return entropy


def outside_git_folder(case):
    """진짜 임시 폴더 — 그 위쪽에 `.git` 이 있으면(이 PC 의 설정에 따라) 건너뛴다."""
    holder = rts.temp_dir()
    case.addCleanup(holder.cleanup)
    folder = Path(holder.name)
    if update_keygen.inside_git_work_tree(folder):
        case.skipTest("건너뜀: 임시 폴더가 git 작업 폴더 안이다")
    return folder


def fake_git_folder(case, *, as_file=False, nested="a/b"):
    """`.git`(폴더 또는 워크트리의 파일)이 있는 가짜 작업 폴더 안의 하위 폴더."""
    holder = rts.temp_dir()
    case.addCleanup(holder.cleanup)
    top = Path(holder.name)
    if as_file:
        (top / ".git").write_text("gitdir: elsewhere\n", encoding="utf-8")
    else:
        (top / ".git").mkdir()
    inner = top / nested
    inner.mkdir(parents=True)
    return top, inner


class WriteFails:
    """쓰면 늘 같은 오류를 던지는 표준 출력·오류 흉내 — 닫힌 파이프·못 쓰는 글자."""

    def __init__(self, error):
        self.error = error
        self.tries = 0

    def write(self, text):
        self.tries += 1
        raise self.error


class OutputSafetyTest(unittest.TestCase):
    """재작업 1(시험 렌즈 Q 의 R2) — 키 파일을 만든 **뒤에** 공개 값을 화면에 쓰다 실패해도(비 UTF-8 파이프·닫힌 파이프) 파일이 있는데 '만들지 못했다' 로 보이지 않는다:
    출력 인코딩이 못 쓰는 글자는 물음표로 바꿔 다시 쓰고(종료 0), 그래도 못 쓰면 키 파일은 그대로 두고 **다른 종료 코드(4)와 ASCII 고정 문장**으로 알린다(공개 값은 `--public-of` 로 다시 본다)."""

    def make(self, label, stdout, stderr):
        seed = rts.canary_seed(label)
        folder = outside_git_folder(self)
        target = folder / "k.txt"
        code = update_keygen.main(["--out", str(target)], entropy=entropy_of(seed), stdout=stdout, stderr=stderr)
        return seed, code, target

    def test_an_output_encoding_that_cannot_write_some_characters_gets_question_marks_and_the_key_file_is_fine(self):
        for encoding in ("ascii", "cp949"):
            with self.subTest(encoding=encoding):
                buffer = io.BytesIO()
                stdout = io.TextIOWrapper(buffer, encoding=encoding, errors="strict", write_through=True)
                err = io.StringIO()
                seed, code, target = self.make("kos-" + encoding, stdout, err)
                self.assertEqual((code, err.getvalue()), (0, ""))
                self.assertEqual(target.read_bytes(), base64.b64encode(seed) + b"\n", "키 파일은 정상이다")
                written = buffer.getvalue()
                public = us.public_key(seed)
                self.assertIn(base64.b64encode(public), written, "공개키는 그대로 보인다")
                self.assertIn(update_sign.key_id_of(public).encode("ascii"), written, "지문도 그대로 보인다")
                self.assertIn(b"?", written, "못 쓰는 글자(긴 줄표 등)는 물음표가 된다")
                rts.assert_no_leak(self, seed, written)

    def test_when_the_output_fails_for_good_the_key_file_stays_and_the_code_and_the_sentence_say_so(self):
        errors = {"broken pipe": BrokenPipeError(errno.EPIPE, "broken pipe"), "os error": OSError(errno.EIO, "input output error"), "closed file": ValueError("I/O operation on closed file")}
        for label, error in errors.items():
            with self.subTest(case=label):
                err = io.StringIO()
                seed, code, target = self.make("kos2", WriteFails(error), err)
                self.assertEqual(update_keygen.EXIT_OUTPUT, 4)
                self.assertEqual(code, update_keygen.EXIT_OUTPUT)
                self.assertEqual(err.getvalue(), update_keygen.MSG_OUTPUT_FAILED + "\n")
                self.assertTrue(err.getvalue().isascii(), "어떤 출력 인코딩으로도 쓸 수 있는 ASCII 고정 문장")
                self.assertEqual(target.read_bytes(), base64.b64encode(seed) + b"\n", "키 파일은 만들어져 있다")
                code, out, again = run_tool(["--public-of", str(target)])
                self.assertEqual((code, again), (0, ""))
                self.assertIn(base64.b64encode(us.public_key(seed)).decode("ascii"), out, "공개 값은 --public-of 로 다시 볼 수 있다")
                rts.assert_no_leak(self, seed, err.getvalue())

    def test_a_pipe_that_fails_only_when_flushed_is_also_an_output_failure(self):
        """닫힌 파이프는 쓰는 순간이 아니라 비울 때 오류가 난다 — 안전한 쓰기가 비우기까지 한다."""
        class FlushFails:
            def __init__(self, error):
                self.error = error

            def write(self, text):
                return len(text)

            def flush(self):
                raise self.error
        for error in (BrokenPipeError(errno.EPIPE, "broken pipe"), OSError(errno.EINVAL, "invalid argument")):
            with self.subTest(error=type(error).__name__):
                err = io.StringIO()
                seed, code, target = self.make("kos5", FlushFails(error), err)
                self.assertEqual((code, err.getvalue()), (update_keygen.EXIT_OUTPUT, update_keygen.MSG_OUTPUT_FAILED + "\n"))
                self.assertEqual(target.read_bytes(), base64.b64encode(seed) + b"\n")

    def test_a_failing_error_stream_never_turns_into_an_exception_on_any_path(self):
        broken = WriteFails(UnicodeEncodeError("ascii", "x", 0, 1, "bad"))
        seed, code, target = self.make("kos3", WriteFails(OSError("x")), broken)
        self.assertEqual(code, update_keygen.EXIT_OUTPUT)
        self.assertTrue(target.is_file(), "화면에 못 써도 키 파일은 있다")
        self.assertEqual(update_keygen.main(["--out", str(target)], entropy=entropy_of(seed), stdout=io.StringIO(), stderr=broken), update_keygen.EXIT_USAGE, "이미 있다는 거절을 못 써도 코드는 그대로")
        self.assertEqual(update_keygen.main(["--bogus"], stdout=io.StringIO(), stderr=broken), update_keygen.EXIT_USAGE)
        self.assertEqual(update_keygen.main(["--public-of", str(target) + ".none"], stdout=io.StringIO(), stderr=broken), update_keygen.EXIT_UNREADABLE)
        self.assertEqual(update_keygen.main(["--public-of", str(target)], stdout=WriteFails(OSError("x")), stderr=broken), update_keygen.EXIT_OUTPUT, "공개 값을 못 쓰는 것도 같은 코드")
        self.assertGreaterEqual(broken.tries, 5)

    def test_a_file_write_failure_is_another_code_and_still_says_the_key_file_was_not_made(self):
        seed = rts.canary_seed("kos4")
        folder = outside_git_folder(self)
        err = io.StringIO()
        with mock.patch("os.fsync", side_effect=OSError("disk full")):
            code = update_keygen.main(["--out", str(folder / "k.txt")], entropy=entropy_of(seed), stdout=io.StringIO(), stderr=err)
        self.assertEqual((code, err.getvalue()), (update_keygen.EXIT_FAILED, "만들지 못했다: 파일을 쓰다 운영체제가 거절했다.\n"))
        self.assertNotEqual(code, update_keygen.EXIT_OUTPUT)
        self.assertFalse((folder / "k.txt").exists())


class WindowsPermissionWarningTest(unittest.TestCase):
    """재작업 1(S-4) — 윈도에서 `0o600` 은 접근 권한을 좁히지 않는다. 도구가 화면에 사실대로 알린다(공용 PC 에서는 폴더 권한을 따로 확인)."""

    def test_the_third_warning_says_the_permission_bits_do_not_narrow_access_on_windows(self):
        self.assertEqual(len(update_keygen.WARNINGS), 3)
        third = update_keygen.WARNINGS[2]
        for word in ("윈도", "0o600", "접근 권한을 좁히지 않는다", "사용자 프로필", "여러 사람이 쓰는 PC", "폴더 권한"):
            self.assertIn(word, third)
        self.assertEqual("\n".join(update_keygen.WARNINGS) + "\n", WARNING_LINES)
        self.assertNotIn(chr(126), third)

    def test_the_warning_is_on_the_screen_of_a_successful_run_and_not_in_the_public_only_view(self):
        folder = outside_git_folder(self)
        code, out, _err = run_tool(["--out", str(folder / "k.txt")], entropy=entropy_of(rts.canary_seed("kgw")))
        self.assertEqual(code, 0)
        self.assertTrue(out.endswith(WARNING_LINES), "경고 셋이 맨 끝에 이 차례로 나온다")
        code, out, _err = run_tool(["--public-of", str(folder / "k.txt")])
        self.assertEqual(code, 0)
        self.assertNotIn("[주의]", out, "공개키·지문만 다시 보는 길에는 경고가 없다")


class GenerateTest(unittest.TestCase):
    def test_the_secret_goes_only_into_the_file_and_the_screen_shows_exactly_the_public_values(self):
        seed = rts.canary_seed("kg1")
        folder = outside_git_folder(self)
        target = folder / "update_signing_key.txt"
        with self.assertNoLogs(level="DEBUG"):
            code, out, err = run_tool(["--out", str(target)], entropy=entropy_of(seed))
        public = us.public_key(seed)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(target.read_bytes(), (rts.seed_b64(seed) + "\n").encode("ascii"), "씨앗 base64 한 줄 44글자 + LF")
        self.assertEqual(len(target.read_bytes()), 45)
        ident = rts.key_id(public)
        self.assertEqual(out, "새 서명 키 쌍을 만들었다 — 역할: 현재 키(current)\n"
                              "비밀 파일: update_signing_key.txt (내용을 어디에도 붙이지 않는다)\n"
                              f"공개키(base64): {base64.b64encode(public).decode()}\n"
                              f"지문(SHA-256 앞 16글자): {ident}\n"
                              "파일을 다시 읽어 같은 공개키가 나오는 것을 확인했다.\n" + WARNING_LINES)
        rts.assert_no_leak(self, seed, out, err)
        self.assertNotIn(str(folder), out, "화면에 폴더 경로를 보이지 않는다(계정 이름이 든 경로가 로그에 남지 않게)")

    def test_spare_only_changes_the_role_label(self):
        seed = rts.canary_seed("kg2")
        folder = outside_git_folder(self)
        code, out, err = run_tool(["--out", str(folder / "spare.txt"), "--spare"], entropy=entropy_of(seed))
        self.assertEqual((code, err), (0, ""))
        self.assertTrue(out.startswith("새 서명 키 쌍을 만들었다 — 역할: 예비 키(spare)\n"))
        self.assertEqual((folder / "spare.txt").read_bytes(), (rts.seed_b64(seed) + "\n").encode("ascii"))
        rts.assert_no_leak(self, seed, out, err)

    def test_the_fingerprint_is_the_apps_key_name_and_has_the_16_hex_shape(self):
        seed = rts.canary_seed("kg3")
        folder = outside_git_folder(self)
        _code, out, _err = run_tool(["--out", str(folder / "k.txt")], entropy=entropy_of(seed))
        found = [line for line in out.splitlines() if line.startswith("지문(SHA-256 앞 16글자): ")]
        self.assertEqual(len(found), 1)
        ident = found[0].split(": ", 1)[1]
        self.assertRegex(ident, r"[0-9a-f]{16}")
        self.assertEqual(ident, keys.key_id_of(us.public_key(seed)))

    def test_the_default_randomness_is_the_operating_systems_and_two_runs_differ(self):
        folder = outside_git_folder(self)
        for name in ("one.txt", "two.txt"):
            code, out, err = run_tool(["--out", str(folder / name)])
            self.assertEqual((code, err), (0, ""))
        first, second = (folder / "one.txt").read_bytes(), (folder / "two.txt").read_bytes()
        self.assertNotEqual(first, second)
        for data in (first, second):
            self.assertEqual(len(data), 45)
            self.assertEqual(len(update_sign.parse_signing_key(data.decode("ascii"))), 32)
        tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
        defaults = [ast.unparse(default) for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "main" for default in node.args.kw_defaults]
        self.assertIn("os.urandom", defaults)

    def test_a_randomness_source_that_gives_the_wrong_length_stops_without_a_file(self):
        folder = outside_git_folder(self)
        for junk in (b"", b"x" * 31, b"x" * 33, "text", None):
            with self.subTest(junk=repr(junk)[:12]):
                code, out, err = run_tool(["--out", str(folder / "k.txt")], entropy=lambda count, junk=junk: junk)
                self.assertEqual((code, out), (1, ""))
                self.assertEqual(err, "만들지 못했다: 난수를 얻지 못했다.\n")
                self.assertFalse((folder / "k.txt").exists())

    def test_an_unexpected_exception_prints_only_its_class_name_and_leaves_no_file(self):
        seed = rts.canary_seed("kg1b")
        folder = outside_git_folder(self)

        def boom(count):
            raise RuntimeError("값:" + rts.seed_b64(seed))
        code, out, err = run_tool(["--out", str(folder / "k.txt")], entropy=boom)
        self.assertEqual((code, out), (1, ""))
        self.assertEqual(err, "예상하지 못한 오류로 멈췄다(종류: RuntimeError). 키 파일을 확인해 주세요.\n")
        self.assertFalse((folder / "k.txt").exists())
        rts.assert_no_leak(self, seed, out, err)

    @unittest.skipIf(os.name == "nt", "건너뜀: 윈도는 파일 권한 비트가 다르다")
    def test_the_file_is_readable_by_the_current_user_only(self):
        folder = outside_git_folder(self)
        run_tool(["--out", str(folder / "k.txt")], entropy=entropy_of(rts.canary_seed("kg4")))
        self.assertEqual(stat.S_IMODE((folder / "k.txt").stat().st_mode), 0o600)


class RefusalTest(unittest.TestCase):
    def refused(self, argv, message, **kwargs):
        calls = entropy_of(rts.canary_seed("refuse"))
        code, out, err = run_tool(argv, entropy=calls, **kwargs)
        self.assertEqual((code, out), (2, ""))
        self.assertEqual(err, message + "\n")
        self.assertEqual(calls.calls, [], "거절할 때는 난수를 뽑지 않는다")
        rts.assert_no_leak(self, rts.canary_seed("refuse"), out, err)

    def test_an_existing_file_is_never_overwritten(self):
        folder = outside_git_folder(self)
        target = folder / "k.txt"
        for content in (b"OLD", b""):
            target.write_bytes(content)
            self.refused(["--out", str(target)], "만들지 않았다: 그 이름의 파일이 이미 있다(덮어쓰지 않는다).")
            self.assertEqual(target.read_bytes(), content)

    def test_an_existing_folder_or_a_dangling_name_is_refused_too(self):
        folder = outside_git_folder(self)
        (folder / "dir").mkdir()
        self.refused(["--out", str(folder / "dir")], "만들지 않았다: 그 이름의 파일이 이미 있다(덮어쓰지 않는다).")
        link = folder / "link.txt"
        try:
            os.symlink(str(folder / "nowhere.txt"), str(link))
        except (OSError, NotImplementedError):
            self.skipTest("건너뜀: 이 PC 는 심볼릭 링크를 만들 수 없다")
        self.refused(["--out", str(link)], "만들지 않았다: 그 이름의 파일이 이미 있다(덮어쓰지 않는다).")
        self.assertFalse((folder / "nowhere.txt").exists(), "끊어진 링크의 대상 자리에 파일을 만들지 않는다")

    def test_inside_a_git_work_tree_is_refused_for_a_git_folder_a_worktree_file_and_the_git_folder_itself(self):
        message = "만들지 않았다: git 작업 폴더 안이다 — 비밀 파일은 저장소 밖에 둔다."
        for as_file in (False, True):
            top, inner = fake_git_folder(self, as_file=as_file)
            with self.subTest(worktree_file=as_file):
                self.refused(["--out", str(inner / "k.txt")], message)
                self.refused(["--out", str(top / "k.txt")], message)
                self.assertEqual([item.name for item in inner.iterdir()], [])
        top, _inner = fake_git_folder(self)
        self.refused(["--out", str(top / ".git" / "k.txt")], message)

    def test_this_very_repository_is_refused(self):
        if not (ROOT / ".git").exists():
            self.skipTest("건너뜀: 이 사본에는 .git 이 없다")
        key_path = ROOT / "never_created_key.txt"
        self.addCleanup(lambda: key_path.unlink() if key_path.exists() else None)            # 가드가 깨져 진짜 난수 키 파일이 저장소 맨 위에 생겨도 시험이 끝나면 지운다(Q 의 참고 N6)
        self.refused(["--out", str(key_path)], "만들지 않았다: git 작업 폴더 안이다 — 비밀 파일은 저장소 밖에 둔다.")
        self.assertFalse(key_path.exists())

    def test_a_relative_path_inside_a_git_folder_is_refused_by_where_it_really_points(self):
        top, inner = fake_git_folder(self)
        old = os.getcwd()
        os.chdir(inner)
        try:
            self.refused(["--out", "k.txt"], "만들지 않았다: git 작업 폴더 안이다 — 비밀 파일은 저장소 밖에 둔다.")
            self.refused(["--out", os.path.join("..", "k.txt")], "만들지 않았다: git 작업 폴더 안이다 — 비밀 파일은 저장소 밖에 둔다.")
        finally:
            os.chdir(old)

    def test_a_missing_folder_is_refused(self):
        folder = outside_git_folder(self)
        self.refused(["--out", str(folder / "nope" / "k.txt")], "만들지 않았다: 파일을 둘 폴더가 없다.")
        self.assertFalse((folder / "nope").exists(), "폴더를 대신 만들지 않는다")

    def test_usage_mistakes_print_the_fixed_sentence_and_never_echo_the_arguments(self):
        text = rts.seed_b64(rts.canary_seed("usage"))
        for argv in ([], ["--out"], ["--out", "a", "--public-of", "b"], ["--spare"], ["--out", "a", text], ["--bogus=" + text], ["--public-of"]):
            with self.subTest(argv=argv[:2]):
                code, out, err = run_tool(argv, entropy=entropy_of(rts.canary_seed("usage")))
                self.assertEqual((code, out), (2, ""))
                self.assertEqual(err, "사용법 오류: --out 파일 [--spare] 또는 --public-of 파일 만 쓴다. 비밀 값은 화면에 보이지 않는다.\n")
                rts.assert_no_leak(self, rts.canary_seed("usage"), out, err)


class InsideGitTest(unittest.TestCase):
    def test_the_search_walks_up_to_the_root_with_injected_file_checks(self):
        present = {os.path.join(os.sep, "work", "repo", ".git")}
        exists = lambda path: path in present            # noqa: E731
        real = lambda path: path                         # noqa: E731
        join = os.path.join
        base = join(os.sep, "work", "repo")
        for inside in (base, join(base, "a"), join(base, "a", "b", "c"), join(base, ".git")):
            self.assertTrue(update_keygen.inside_git_work_tree(inside, exists=exists, realpath=real), inside)
        for outside in (join(os.sep, "work"), join(os.sep, "work", "other", "x"), os.sep):
            self.assertFalse(update_keygen.inside_git_work_tree(outside, exists=exists, realpath=real), outside)

    def test_a_real_symlink_that_points_into_a_git_folder_is_refused_with_the_default_realpath(self):
        """QK02(Q 의 R5) — 진짜 링크로 저장소 폴더 안에 쓰려 해도 거절한다: 주입한 가짜 `realpath` 만이 아니라 **기본값 배선**(링크를 실제 위치로 따라감)도 본다."""
        holder = rts.temp_dir()
        self.addCleanup(holder.cleanup)
        base = Path(holder.name)
        if update_keygen.inside_git_work_tree(base):
            self.skipTest("건너뜀: 임시 폴더가 git 작업 폴더 안이다")
        top = base / "repo"
        (top / ".git").mkdir(parents=True)
        (top / "sub").mkdir()
        link = base / "link"
        try:
            os.symlink(str(top / "sub"), str(link), target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("건너뜀: 이 PC 는 심볼릭 링크를 만들 수 없다")
        code, out, err = run_tool(["--out", str(link / "k.txt")], entropy=entropy_of(rts.canary_seed("kg-link")))
        self.assertEqual((code, out, err), (2, "", "만들지 않았다: git 작업 폴더 안이다 — 비밀 파일은 저장소 밖에 둔다.\n"))
        self.assertFalse((top / "sub" / "k.txt").exists(), "링크를 통해서도 저장소 안에 비밀 파일이 생기지 않는다")

    def test_the_search_follows_symlinks_by_the_real_path(self):
        base = os.path.join(os.sep, "work", "repo")
        exists = lambda path: path == os.path.join(base, ".git")   # noqa: E731
        real = lambda path: base if path.endswith("link") else path   # noqa: E731
        self.assertTrue(update_keygen.inside_git_work_tree(os.path.join(os.sep, "somewhere", "link"), exists=exists, realpath=real))


class WriteFailureTest(unittest.TestCase):
    def test_a_failed_flush_to_disk_removes_the_half_written_file_and_says_so(self):
        folder = outside_git_folder(self)
        target = folder / "k.txt"
        seed = rts.canary_seed("kg5")
        with mock.patch.object(update_keygen.os, "fsync", side_effect=OSError("disk")):
            code, out, err = run_tool(["--out", str(target)], entropy=entropy_of(seed))
        self.assertEqual((code, out), (1, ""))
        self.assertEqual(err, "만들지 못했다: 파일을 쓰다 운영체제가 거절했다.\n")
        self.assertFalse(target.exists(), "반쯤 쓴 비밀 파일을 남기지 않는다")
        rts.assert_no_leak(self, seed, out, err)

    def test_a_read_back_that_does_not_match_removes_the_file(self):
        folder = outside_git_folder(self)
        target = folder / "k.txt"
        seed = rts.canary_seed("kg6")
        with mock.patch.object(update_keygen, "_read_back", return_value=b"\x00" * 32):
            code, out, err = run_tool(["--out", str(target)], entropy=entropy_of(seed))
        self.assertEqual((code, out), (1, ""))
        self.assertEqual(err, "만들지 못했다: 쓴 파일을 다시 읽으니 맞지 않다.\n")
        self.assertFalse(target.exists())
        rts.assert_no_leak(self, seed, out, err)

    def test_the_opener_asks_for_owner_only_permissions_on_every_platform(self):
        """POSIX 에서만 권한 비트가 쓰이지만 코드가 0o600 을 요구하는 것은 어느 플랫폼에서나 볼 수 있다."""
        real_open, seen = os.open, []

        def fake_open(name, flags, mode=0o777):
            seen.append((name, flags, mode))
            return real_open(os.devnull, os.O_RDONLY)
        with mock.patch.object(update_keygen.os, "open", fake_open):
            handle = update_keygen._opener("x", os.O_WRONLY)
        os.close(handle)
        self.assertEqual(seen, [("x", os.O_WRONLY, 0o600)])

    def test_the_file_is_created_exclusively(self):
        folder = outside_git_folder(self)
        target = folder / "k.txt"
        update_keygen._write_new_file(str(target), b"first\n")
        with self.assertRaises(FileExistsError):
            update_keygen._write_new_file(str(target), b"second\n")
        self.assertEqual(target.read_bytes(), b"first\n")


class PublicOfTest(unittest.TestCase):
    def test_public_of_shows_only_the_public_key_and_the_fingerprint_for_both_formats(self):
        seed = rts.canary_seed("kg7")
        folder = outside_git_folder(self)
        public = us.public_key(seed)
        for name, text in (("raw.txt", rts.seed_b64(seed) + "\n"), ("key.pem", rts.seed_pem(seed))):
            path = folder / name
            path.write_text(text, encoding="utf-8", newline="\n")
            with self.subTest(file=name):
                code, out, err = run_tool(["--public-of", str(path)])
                self.assertEqual((code, err), (0, ""))
                self.assertEqual(out, f"공개키(base64): {base64.b64encode(public).decode()}\n지문(SHA-256 앞 16글자): {rts.key_id(public)}\n")
                rts.assert_no_leak(self, seed, out, err)

    def test_two_copies_of_one_secret_show_the_same_fingerprint_and_a_different_secret_does_not(self):
        folder = outside_git_folder(self)
        texts = {"a1": rts.seed_b64(rts.canary_seed("kg8")) + "\n", "a2": rts.seed_b64(rts.canary_seed("kg8")) + "\n", "b": rts.seed_b64(rts.canary_seed("kg8b")) + "\n"}
        shown = {}
        for name, text in texts.items():
            (folder / name).write_text(text, encoding="utf-8", newline="\n")
            shown[name] = run_tool(["--public-of", str(folder / name)])[1]
        self.assertEqual(shown["a1"], shown["a2"])
        self.assertNotEqual(shown["a1"], shown["b"])

    def test_a_missing_or_malformed_file_gives_one_fixed_sentence_with_no_trace_of_the_value(self):
        seed = rts.canary_seed("kg9")
        folder = outside_git_folder(self)
        bad = folder / "bad.txt"
        bad.write_text(rts.seed_b64(seed) + "AA\n", encoding="utf-8", newline="\n")
        for path in (folder / "none.txt", bad, folder):
            with self.subTest(path=path.name):
                code, out, err = run_tool(["--public-of", str(path)])
                self.assertEqual((code, out), (3, ""))
                self.assertEqual(err, "읽지 못했다: 파일이 없거나 서명 키의 형식을 알아볼 수 없다.\n")
                rts.assert_no_leak(self, seed, out, err)


class RoundTripTest(unittest.TestCase):
    def test_a_generated_file_signs_a_manifest_and_the_apps_verifier_accepts_it(self):
        seed = rts.canary_seed("rt1")
        folder = outside_git_folder(self)
        key_file = folder / "k.txt"
        run_tool(["--out", str(key_file)], entropy=entropy_of(seed))
        ident = rts.key_id(us.public_key(seed))
        sign_out = folder / "sign"
        sign_out.mkdir()
        path = sign_out / "update-manifest.json"
        path.write_bytes(rts.manifest_bytes(seed))
        code, _out, err = rts.Capture(update_sign.main)(["--manifest", str(path)], environ={"UPDATE_SIGNING_KEY": key_file.read_text(encoding="ascii")}, which=lambda name: None)
        self.assertEqual((code, err), (0, ""))
        signature = (sign_out / "update-manifest.json.sig").read_bytes()
        verified = manifest.read_and_verify(path.read_bytes(), signature, keyring=keys.Keyring([(keys.ROLE_CURRENT, us.public_key(seed))]), channels=manifest.CHANNELS_OFFLINE)
        self.assertEqual(verified.key_id, ident)


class SourceShapeTest(unittest.TestCase):
    def test_no_logging_no_traceback_no_print_and_no_secret_in_any_f_string(self):
        tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
        imported = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
        imported |= {(node.module or "").split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        self.assertFalse(imported & {"logging", "traceback", "pdb", "pprint", "warnings", "random"}, imported)
        calls = [ast.unparse(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)]
        self.assertNotIn("print", calls)
        for node in ast.walk(tree):
            if isinstance(node, ast.JoinedStr):
                used = {part.id for part in ast.walk(node) if isinstance(part, ast.Name)}
                self.assertFalse(used & {"seed", "secret", "text", "data", "line"}, f"f-문자열에 비밀 이름이 든다 (줄 {node.lineno})")


@unittest.skipUnless(sys.executable, "파이썬 실행 파일이 필요하다")
class EndToEndTest(unittest.TestCase):
    def run_script(self, *args, stdout=subprocess.PIPE):
        environ = {key: value for key, value in os.environ.items() if not key.startswith("UPDATE_")}
        environ.pop("PYTHONPATH", None)
        environ["PYTHONUTF8"] = "1"
        environ["PYTHONIOENCODING"] = "utf-8"            # 부모 환경(예: cp949)에 흔들리지 않게 자식의 입출력 인코딩을 못박는다(Q 의 R3)
        return subprocess.run([sys.executable, "-X", "utf8", str(SCRIPT), *args], stdout=stdout, stderr=subprocess.PIPE, env=environ, timeout=300)

    def test_a_closed_output_pipe_keeps_the_key_file_and_ends_with_code_4_and_the_ascii_sentence(self):
        """재작업 1(Q 의 R2) — 읽는 쪽이 이미 닫힌 파이프로 진짜 하위 프로세스를 돌린다: 키 파일은 그대로 있고 종료 코드는 4(끝날 때 다시 비우다 120 으로 바뀌지 않는다)·표준 오류에는 ASCII 고정 문장뿐이다."""
        folder = outside_git_folder(self)
        target = folder / "k.txt"
        read_end, write_end = os.pipe()
        os.close(read_end)
        try:
            done = self.run_script("--out", str(target), stdout=write_end)
        finally:
            os.close(write_end)
        text = done.stderr.decode("utf-8", "replace")
        self.assertEqual(done.returncode, 4, text)
        secret = target.read_text(encoding="ascii").strip()
        self.assertEqual(len(secret), 44, "키 파일은 만들어져 있다")
        self.assertIn(update_keygen.MSG_OUTPUT_FAILED, text)
        for word in ("Traceback", "Exception ignored", "BrokenPipe"):
            self.assertNotIn(word, text)
        for window in range(0, 44 - 7):
            self.assertNotIn(secret[window:window + 8], text, "비밀의 조각이 오류 글에 있다")

    def test_the_script_runs_for_real_creates_the_file_and_shows_only_public_values(self):
        folder = outside_git_folder(self)
        target = folder / "k.txt"
        done = self.run_script("--out", str(target))
        out = done.stdout.decode("utf-8").replace("\r\n", "\n")
        self.assertEqual((done.returncode, done.stderr), (0, b""), out)
        secret = target.read_text(encoding="ascii").strip()
        self.assertEqual(len(secret), 44)
        self.assertNotIn(secret, out)
        for window in range(0, 44 - 7):
            self.assertNotIn(secret[window:window + 8], out, "비밀의 조각이 화면에 있다")
        public = base64.b64encode(update_sign.public_key(update_sign.parse_signing_key(secret))).decode()
        self.assertIn(f"공개키(base64): {public}\n", out)
        again = self.run_script("--out", str(target))
        self.assertEqual(again.returncode, 2)
        self.assertEqual(target.read_text(encoding="ascii").strip(), secret, "다시 돌려도 덮어쓰지 않는다")

    def test_the_script_refuses_to_write_inside_this_repository(self):
        if not (ROOT / ".git").exists():
            self.skipTest("건너뜀: 이 사본에는 .git 이 없다")
        key_path = ROOT / "never_created_key_2.txt"
        self.addCleanup(lambda: key_path.unlink() if key_path.exists() else None)            # 가드가 깨져도 진짜 키 파일을 남기지 않는다(Q 의 참고 N6)
        done = self.run_script("--out", str(key_path))
        self.assertEqual(done.returncode, 2)
        self.assertFalse(key_path.exists())
        self.assertNotIn(b"Traceback", done.stderr)


if __name__ == "__main__":
    unittest.main()
