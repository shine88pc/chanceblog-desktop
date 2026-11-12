"""데이터 폴더가 사용자 프로필 밖이면 `doctor` 가 알린다(PCSEC1 M1 — 보안 조사: 앱이 NTFS 권한을 설정·확인하지 않고 폴더 상속에 의존한다).

'같은 PC 의 다른 사용자가 읽을 수 있어요 — 기본 위치를 권해요' 주의를 **문자열 경로 비교만으로** 낸다: 파일 시스템·`icacls`·하위 프로세스를 부르지 않고 권한도 바꾸지 않는다.
프로필 = Windows 는 `%LOCALAPPDATA%`·`%APPDATA%`·`%USERPROFILE%`, 그 밖은 `XDG_DATA_HOME`·`HOME` 아래. 프로필 위치를 모르면(환경 변수가 빈 시험) 경고하지 않는다.
시험은 가짜 경로 인자·가짜 환경 모음으로 도는 순수 문자열 비교라 어느 운영체제(리눅스 CI 포함)에서 돌려도 같다.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import outgoing_support as og  # noqa: E402
import service_support as ss  # noqa: E402

from chanceblog_desktop.service import doctor  # noqa: E402
from chanceblog_desktop.service.context import outside_user_profile  # noqa: E402

WIN = {"LOCALAPPDATA": "C:/Users/kim/AppData/Local", "APPDATA": "C:/Users/kim/AppData/Roaming", "USERPROFILE": "C:/Users/kim"}
POSIX = {"HOME": "/home/kim", "XDG_DATA_HOME": "/home/kim/.local/share"}
BOTH = {**WIN, **POSIX}                    # 윈도 이름과 리눅스 이름을 함께 준다 — 판정이 `os.name` 으로 이름을 고르므로 어느 운영체제(CI 우분투 포함)에서 돌려도 같은 뜻이다(PCSEC1V D1)
B = chr(92)


def win(text):
    return text.replace("/", B)


class OutsideProfileTest(unittest.TestCase):
    def test_places_inside_the_windows_profile_are_not_outside(self):
        for path in ("C:/Users/kim/AppData/Local/ChanceblogDesktop", "C:/Users/kim/AppData/Roaming/x", "C:/Users/kim/Documents/글 데이터", "C:/Users/kim", "C:/Users/kim/AppData/Local",
                     "c:/users/KIM/appdata/local/ChanceblogDesktop", "C:/Users/kim/AppData/Local/../Local/x", "C:/Users/kim/./Desktop/데이터/"):
            for form in (path, win(path)):
                with self.subTest(path=form):
                    self.assertFalse(outside_user_profile(form, WIN, windows=True))

    def test_places_outside_the_windows_profile_are_outside(self):
        for path in ("C:/work/data", "D:/ChanceblogDesktop", "C:/Users/kim2/x", "C:/Users/Public/x", "C:/Users/kim/../lee/x", "C:/ProgramData/ChanceblogDesktop", "//server/share/x", "C:/",
                     "C:/Users/kimchi", "C:/Users"):
            for form in (path, win(path)):
                with self.subTest(path=form):
                    self.assertTrue(outside_user_profile(form, WIN, windows=True))

    def test_a_redirected_roaming_folder_counts_as_profile_even_when_it_is_outside_the_user_folder(self):
        env = {"APPDATA": "D:/redirected/kim/AppData/Roaming", "USERPROFILE": "C:/Users/kim"}              # 회사 PC 처럼 APPDATA 가 사용자 폴더 밖으로 리다이렉트된 경우
        for path in ("D:/redirected/kim/AppData/Roaming/ChanceblogDesktop", "D:/redirected/kim/AppData/Roaming"):
            self.assertFalse(outside_user_profile(path, env, windows=True), path)
        self.assertTrue(outside_user_profile("D:/redirected/lee/AppData/Roaming/x", env, windows=True))
        self.assertFalse(outside_user_profile("C:/Users/kim/data", env, windows=True))

    def test_the_posix_profile_is_home_and_the_xdg_folder(self):
        for path in ("/home/kim/.local/share/ChanceblogDesktop", "/home/kim/data", "/home/kim"):
            self.assertFalse(outside_user_profile(path, POSIX, windows=False), path)
        for path in ("/tmp/x", "/home/kimchi/x", "/home/lee/x", "/var/lib/x", "/home/kim/../lee/x"):
            self.assertTrue(outside_user_profile(path, POSIX, windows=False), path)

    def test_an_explicit_home_argument_adds_a_profile_root(self):
        self.assertFalse(outside_user_profile("/srv/me/data", {}, windows=False, home="/srv/me"))
        self.assertTrue(outside_user_profile("/srv/other/data", {}, windows=False, home="/srv/me"))

    def test_without_any_profile_information_it_never_warns(self):
        for env in ({}, {"LOCALAPPDATA": "", "USERPROFILE": "   "}):
            self.assertFalse(outside_user_profile("C:/work/data", env, windows=True))
            self.assertFalse(outside_user_profile("/tmp/x", env, windows=False))

    def test_it_never_raises_and_never_touches_the_file_system(self):
        with og.Tripwire() as wire:
            for path in ("", "..", "\x00", "C:", "//", "x" * 5000, "C:/Users/kim/\ud800"):
                self.assertIn(outside_user_profile(path, WIN, windows=True), (True, False))
        self.assertEqual(wire.calls, [])

    def test_the_default_comparison_uses_the_real_environment_only_when_none_is_given(self):
        home = os.environ.get("USERPROFILE" if os.name == "nt" else "HOME")                      # 시험을 돌리는 운영체제의 프로필 위치(윈도 USERPROFILE·그 밖 HOME)
        if home:
            self.assertFalse(outside_user_profile(str(Path(home) / "x")))


class DoctorTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.ctx = ss.make_ctx(self.tmp, repo=None)

    def test_a_folder_outside_the_profile_gets_a_warning_with_the_plain_sentence_and_what_to_do(self):
        self.ctx.env = dict(BOTH)
        self.ctx.workspace.root.mkdir(parents=True)
        check = doctor._check_data_dir(self.ctx)
        self.assertEqual((check.name, check.status, check.code), ("데이터 폴더", "warn", ""))
        self.assertIn("같은 PC 의 다른 사용자가 읽을 수 있어요", check.message)
        self.assertIn("기본 위치를 권해요", check.message)
        self.assertIn(str(self.ctx.workspace.root), check.message)
        self.assertIn("기본 위치", check.action)
        self.assertIn("폴더 권한은 앱이 바꾸지 않습니다", check.action)

    def test_a_folder_that_does_not_exist_yet_gets_the_same_warning(self):
        self.ctx.env = {"HOME": "/home/kim", "XDG_DATA_HOME": "/home/kim/.local/share", "LOCALAPPDATA": "C:/Users/kim/AppData/Local"}
        check = doctor._check_data_dir(self.ctx)
        self.assertEqual(check.status, "warn")
        self.assertIn("아직 없습니다", check.message)
        self.assertIn("같은 PC 의 다른 사용자가 읽을 수 있어요", check.message)

    def test_a_folder_inside_the_profile_or_with_an_unknown_profile_stays_ok(self):
        self.ctx.workspace.root.mkdir(parents=True)
        names = ("USERPROFILE", "LOCALAPPDATA") if os.name == "nt" else ("HOME", "XDG_DATA_HOME")                    # 시험을 돌리는 운영체제가 쓰는 이름(임시 폴더 경로도 그 운영체제의 모양이다) — 어디서나 '프로필 안' 이다
        self.ctx.env = {name: str(self.tmp) for name in names}
        self.assertEqual(doctor._check_data_dir(self.ctx).status, "ok")
        self.ctx.env = {}
        check = doctor._check_data_dir(self.ctx)
        self.assertEqual((check.status, check.message.startswith("쓸 수 있습니다")), ("ok", True))

    def test_the_check_runs_in_the_whole_doctor_and_does_not_fail_it(self):
        self.ctx.env = dict(BOTH)
        results = doctor.run_doctor(self.ctx)
        found = [item for item in results if item.name == "데이터 폴더"]
        self.assertEqual([item.status for item in found], ["warn"])
        self.assertTrue(doctor.doctor_ok(results), "주의는 점검을 실패로 만들지 않는다")

    def test_the_same_inputs_warn_whichever_operating_system_the_check_thinks_it_runs_on(self):
        """CI 우분투 교훈(PCSEC1V D1): 판정이 `os.name` 으로 환경 변수 이름을 고르는데 시험이 윈도 이름만 주면 우분투에서 빨개졌다. 두 이름을 함께 주고, 판정을 윈도·리눅스 뜻으로 번갈아 고정해도 같은 '주의' 임을 직접 확인한다."""
        original = doctor.outside_user_profile
        self.ctx.workspace.root.mkdir(parents=True)
        self.ctx.env = dict(BOTH)
        for windows in (True, False):
            with self.subTest(windows=windows):
                forced = lambda path, env=None, **kwargs: original(path, env, windows=windows, **kwargs)  # noqa: E731
                with mock.patch.object(doctor, "outside_user_profile", forced):
                    check = doctor._check_data_dir(self.ctx)
                self.assertEqual((check.status, check.code), ("warn", ""))
                self.assertIn("같은 PC 의 다른 사용자가 읽을 수 있어요", check.message)

    def test_the_check_calls_no_subprocess_and_changes_no_permission(self):
        self.ctx.env = dict(BOTH)
        self.ctx.workspace.root.mkdir(parents=True)
        before = ss.tree_snapshot(self.tmp)
        with og.Tripwire() as wire:
            doctor._check_data_dir(self.ctx)
        self.assertEqual(wire.calls, [])
        self.assertEqual(ss.tree_snapshot(self.tmp), before)
        import ast
        source = (ss.ROOT / "src" / "chanceblog_desktop" / "service" / "context.py").read_text(encoding="utf-8")
        function = next(node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef) and node.name == "outside_user_profile")
        code = chr(10).join(ast.unparse(node) for node in function.body[1:])                  # 설명 글(docstring)은 뺀 코드만
        for word in ("icacls", "subprocess", "chmod", "os.stat", "exists(", "realpath", "resolve(", "Path(", "open("):
            self.assertNotIn(word, code, f"문자열 비교만 한다: {word}")


if __name__ == "__main__":
    unittest.main()
