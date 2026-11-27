"""`update/apply.py` 의 Inno Setup 어댑터 시험(UPDATE 설계서 3-8, v1update4 U-4, 결정 D-850 이상) — **진짜 설치 도구·진짜 Setup 은 한 번도 띄우지 않는다**(시험은 `subprocess.Popen` 대역과 임시 폴더의 가짜 Setup 파일만 쓰고,
윈도에서만 도는 통합 시험 하나가 임시 폴더의 `.cmd` 가짜 Setup 을 진짜 `launch_setup` 으로 띄운다).

지키는 것:
  1) 명령: 고정 인자 목록(`INNO_SILENT_ARGS` 다섯 — 설치 쪽과 같게 `/SP-` 포함 + `/LOG=` 하나)·셸 없음·문자열 한 줄이 아닌 목록 하나·경로는 우리가 만든 폴더의 우리가 정한 이름뿐(Setup 은 매니페스트가 정한 이름 — 그 이름 속 판도 이 판,
     로그는 같은 폴더의 고정 이름 둘 중 하나). `launch_setup` 도 어댑터에만 기대지 않고 Setup 의 파일 이름 규칙·네트워크(UNC) 경로를 한 번 더 본다(독립 검증 S R6).
  2) 끊어서 띄우기: 윈도는 `DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP`, 그 밖은 새 세션, `close_fds`, 표준 입출력은 모두 NUL(출력은 읽지 않고 종료 코드는 기다리지 않는다 — 프로세스 개체에 닿으면 시험이 빨개진다).
  3) 어댑터: 띄우기 직전 재해시·역할·이름·방향(업데이트는 올림, 복구는 내림)·버전·종류 검사 — 어느 하나라도 틀리면 하위 프로세스를 부르기 전에 `UPDATE_APPLY_FAILED`(이유 이름 하나, 경로·오류 글 0). 복구는 보관한 이전 Setup 을 같은 방식으로.
  4) 관문: 스위치가 꺼져 있으면 `UPDATE_DISABLED` 로 하위 프로세스를 부르기 전에 끝난다. 설치 도구를 띄우는 호출은 이 한 함수뿐이다.
  5) **상태 기계 연결**(지시서 5): 적용 → `HANDED_OFF`(앱이 곧 끝남) → 다음 시작의 `note_boot` — Setup 이 조용히 실패하면 '적용되지 않았어요', 새 판이 두 번 정상 표식 없이 켜지면 세 번째 시작에 복구 안내, 복구는 보관한 이전 Setup 을 띄운다.
     복구도 '띄웠다' 까지만 기록한다(`rollback_launched`, 표식은 그대로) — 다음 시작에서 실행 중인 판이 되돌릴 판이면 `rolled_back` 으로 확정하고, 새 판이 그대로 켜지면(복구 Setup 이 조용히 안 돌았다) 복구 안내가 다시 뜬다(독립 검증 S R4).
  6) `velopack` 매니페스트는 읽되(이미 서명된 매니페스트의 모양을 깨지 않는다) 어떤 설치 종류도 그것을 적용 가능하게 만들지 않고 받기·백업 전에 거절된다. 무음 인자는 설치 구현 갈래(`packaging/pkgcommon.py`)와 같은 값이어야 한다(그쪽에 이름이 생기면 짝 시험이 켜진다).
네트워크 없이 돈다.
"""
import ast
import dataclasses
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import traceback
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "packaging"))

import capability_support as cap  # noqa: E402
import test_update_flow as tf  # noqa: E402
import update_flow_support as fs  # noqa: E402
import update_support as us  # noqa: E402

import pkgcommon  # noqa: E402

from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.service import backup_flow, update_flow  # noqa: E402
from chanceblog_desktop.update import apply, health, keys, machine, recovery, source, state  # noqa: E402
from chanceblog_desktop.update import manifest as manifest_module  # noqa: E402

SRC = ROOT / "src" / "chanceblog_desktop"
SETUP_101 = "ChanceBlogDesktop-1.0.1-Setup.exe"
SETUP_100 = "ChanceBlogDesktop-1.0.0-Setup.exe"
FIXED_ARGS = ["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-", "/CLOSEAPPLICATIONS"]       # 설치 구현 갈래 `INNO_SILENT_UPDATE_ARGS` 와 같은 다섯·같은 순서(러너 측정 M05·M09·M19 가 모두 `/SP-` 를 넣었다)
BS = chr(92)                                                                                       # 백슬래시 — 윈도 경로 글을 소스에 이스케이프 없이 조립한다


class NeverTouched:
    """프로세스 개체 대역 — 어떤 속성에 닿아도(`poll`·`wait`·`communicate`·`returncode`·`pid`·`stdout` …) 시험이 빨개진다: 앱은 Setup 의 종료 코드·출력을 보지 않는다."""

    def __getattr__(self, name):
        raise AssertionError(f"프로세스 개체의 {name} 에 닿았다 — 앱은 Setup 을 기다리거나 읽지 않는다")


class FakePopen:
    """`subprocess.Popen` 대역 — 부른 인자를 기록하고 아무것도 띄우지 않는다. `error` 가 있으면 그것을 낸다."""

    def __init__(self, error=None):
        self.calls = []
        self.error = error
        self.process = NeverTouched()

    def __call__(self, command, **kwargs):
        self.calls.append((list(command) if isinstance(command, (list, tuple)) else command, dict(kwargs)))
        if self.error is not None:
            raise self.error
        return self.process


def older_release(kind="inno"):
    """이미 만료된 이전 릴리스(복구는 만료를 보지 않는다)."""
    return fs.Release("1.0.0", min_version="0.9.0", issued="2026-06-01T03:00:00Z", expires="2026-11-28T03:00:00Z", kind=kind)


def make_staged(root, release=None, *, folder_name="staging-run"):
    """받아 검증한 모양의 `StagedUpdate` 하나 — 임시 폴더에 가짜 Setup(릴리스가 서명한 본문)을 놓는다."""
    release = release or fs.Release("1.0.1")
    verified = manifest_module.read_and_verify(release.manifest_bytes, release.signature, keyring=fs.RING)
    folder = Path(root) / folder_name
    folder.mkdir(parents=True, exist_ok=True)
    name = f"ChanceBlogDesktop-{release.version}-Setup.exe"
    (folder / name).write_bytes(release.bodies[name])
    return source.StagedUpdate(folder, {"setup": folder / name}, verified)


class LaunchCase(unittest.TestCase):
    """진짜 `subprocess.Popen` 을 대역으로 바꿔 두고 업데이트 설치 스위치를 임시로 켠 바탕 — 대역이 기록한 것만 본다."""

    def setUp(self):
        holder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(holder.cleanup)
        self.tmp = Path(holder.name)
        self.popen = FakePopen()
        patcher = mock.patch.object(subprocess, "Popen", self.popen)
        patcher.start()
        self.addCleanup(patcher.stop)
        cap.switch_on("UPDATE_APPLY")
        self.addCleanup(cap.switch_off, "UPDATE_APPLY")

    def paths(self, folder_name="staging-run"):
        folder = self.tmp / folder_name
        folder.mkdir(parents=True, exist_ok=True)
        setup = folder / SETUP_101
        setup.write_bytes(b"not a real setup program")
        return setup, folder / apply.UPDATE_LOG_NAME

    def refusal(self, call, *args, **kwargs):
        with self.assertRaises(AppError) as caught:
            call(*args, **kwargs)
        return caught.exception


class CommandTest(LaunchCase):
    def test_the_fixed_arguments_and_log_names_are_the_documented_ones(self):
        self.assertEqual(apply.INNO_SILENT_ARGS, tuple(FIXED_ARGS))
        self.assertEqual(apply.INNO_SILENT_ARGS, ("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-", "/CLOSEAPPLICATIONS"), "설치 쪽 `INNO_SILENT_UPDATE_ARGS` 와 같은 다섯 인자·같은 순서")
        self.assertEqual(apply.LOG_SWITCH, "/LOG=")
        self.assertEqual((apply.UPDATE_LOG_NAME, apply.RECOVERY_LOG_NAME), ("setup-update.log", "setup-recovery.log"))
        self.assertEqual(len(set(apply.INNO_SILENT_ARGS)), 5)
        self.assertIn("/SP-", apply.INNO_SILENT_ARGS, "시작 확인창을 끄는 인자 — 러너 측정 M05·M09·M19 가 모두 넣었고 설치 쪽도 넣는다(독립 검증 S R1)")
        self.assertLess(apply.INNO_SILENT_ARGS.index("/SP-"), apply.INNO_SILENT_ARGS.index("/CLOSEAPPLICATIONS"), "무음 설치 인자 넷 다음에 업데이트용 추가 인자 — 설치 쪽 상수의 순서")
        self.assertFalse([arg for arg in apply.INNO_SILENT_ARGS if "=" in arg or " " in arg or not arg.startswith("/")], "고정 인자에는 값·공백이 없다 — 경로는 /LOG= 한 칸에만 들어간다")

    def test_the_command_is_one_list_the_setup_then_the_fixed_arguments_then_the_log_argument(self):
        setup, log = self.paths()
        command = apply.inno_command(setup, log)
        self.assertIsInstance(command, list)
        self.assertEqual(command, [str(setup), *FIXED_ARGS, "/LOG=" + str(log)])
        self.assertTrue(all(isinstance(item, str) for item in command))
        self.assertEqual(command[1:6], FIXED_ARGS)
        self.assertEqual(self.popen.calls, [], "명령을 만드는 일은 아무것도 띄우지 않는다")

    def test_a_folder_with_spaces_and_korean_letters_still_gives_exactly_six_elements(self):
        """(옛 이름 그대로 — 시험 id 를 지키려고) 고정 인자가 넷에서 다섯(`/SP-` 추가)이 되어 요소는 이제 일곱이다 — 공백·한글이 든 폴더여도 요소 수가 그대로이고 경로는 첫 칸과 `/LOG=` 한 칸에만 든다."""
        setup, log = self.paths("업데이트 받은 곳 with spaces")
        command = apply.inno_command(setup, log)
        self.assertEqual(len(command), 7)
        self.assertEqual(command[0], str(setup))
        self.assertEqual(command[-1], "/LOG=" + str(log))
        self.assertIn(" ", command[-1])

    def test_the_command_does_not_depend_on_the_environment_or_the_working_folder(self):
        setup, log = self.paths()
        before = apply.inno_command(setup, log)
        with mock.patch.dict(os.environ, {"INNO_EXTRA": "/X", "UPDATE_ARGS": "/Y", "SETUP_ARGS": "/Z"}):
            self.assertEqual(apply.inno_command(setup, log), before)
        self.assertEqual(apply.inno_command(setup, str(log)), before, "경로를 글로 줘도 같다")

    def test_unsafe_paths_are_refused_by_one_reason_word_before_any_process_is_started(self):
        setup, log = self.paths()
        other = self.tmp / "other-folder"
        other.mkdir()
        nowhere = self.tmp / "nowhere"
        folder_as_setup = self.tmp / "dir-run"
        (folder_as_setup / SETUP_101).mkdir(parents=True)
        cases = (
            ("상대 경로", SETUP_101, log, "path_not_absolute"),
            ("다른 폴더의 로그", setup, other / apply.UPDATE_LOG_NAME, "log_path"),
            ("우리 이름이 아닌 로그", setup, setup.parent / "evil.log", "log_path"),
            ("Setup 이 없다", nowhere / SETUP_101, nowhere / apply.UPDATE_LOG_NAME, "setup_not_a_file"),
            ("폴더가 Setup 자리에", folder_as_setup / SETUP_101, folder_as_setup / apply.UPDATE_LOG_NAME, "setup_not_a_file"),
            ("널 문자", str(setup) + "\x00", log, "path_type"),
            ("빈 글", "", log, "path_type"),
            ("None", None, log, "path_type"),
            ("숫자", 5, log, "path_type"),
            ("바이트", b"C:/x/setup.exe", log, "path_type"),
            ("로그가 None", setup, None, "path_type"),
        )
        for label, one, two, reason in cases:
            with self.subTest(label=label):
                error = self.refusal(apply.inno_command, one, two)
                self.assertEqual((error.code, error.detail), ("UPDATE_APPLY_FAILED", reason))
        self.assertEqual(self.popen.calls, [])

    def test_a_link_in_place_of_the_setup_is_not_followed(self):
        setup, log = self.paths()
        with mock.patch.object(health, "_is_link", return_value=True):
            self.assertEqual(self.refusal(apply.inno_command, setup, log).detail, "setup_not_a_file")
        link = setup.parent / "ChanceBlogDesktop-1.0.2-Setup.exe"       # 링크의 이름도 Setup 이름 규칙 모양이어야 '링크라서' 거절되는 것이 보인다(이름이 틀리면 이름 검사가 먼저 거절한다)
        try:
            os.symlink(setup, link)
        except (OSError, NotImplementedError):
            return                                     # 이 PC 에서 링크를 만들 수 없다(윈도 권한) — 위의 가짜 링크 판정이 대신 지킨다
        self.assertEqual(self.refusal(apply.inno_command, link, setup.parent / apply.UPDATE_LOG_NAME).detail, "setup_not_a_file")
        odd = setup.parent / "linked.exe"
        os.symlink(setup, odd)
        self.assertEqual(self.refusal(apply.inno_command, odd, setup.parent / apply.UPDATE_LOG_NAME).detail, "setup_name", "이름이 규칙에 맞지 않는 링크는 이름 검사가 먼저 거절한다")

    def test_a_file_that_is_not_named_like_our_setup_is_refused_before_the_file_system_is_touched(self):
        """독립 검증 S R6 — 이름 규칙(`SETUP_NAME`)을 아는 곳이 어댑터 하나뿐이면 `launch_setup` 을 직접 부르는 길에는 방어가 없었다(`evil.exe`·`.cmd`·`.EXE`·`.exe.exe`·끝의 점/공백·`:` 스트림이 모두 떴다).
        이제 명령을 만드는 함수와 `launch_setup` 이 둘 다 이름 변형을 `setup_name` 으로, 파일 시스템을 보기도 전에 거절한다."""
        setup, log = self.paths()
        folder = str(setup.parent) + os.sep
        names = (("다른 이름", "evil.exe"), ("스크립트", "ChanceBlogDesktop-1.0.1-Setup.cmd"), ("대문자 확장자", "ChanceBlogDesktop-1.0.1-Setup.EXE"), ("이중 확장자", SETUP_101 + ".exe"),
                 ("끝의 점", SETUP_101 + "."), ("끝의 공백", SETUP_101 + " "), ("스트림 이름", SETUP_101 + ":stream"), ("버전 없는 이름", "ChanceBlogDesktop-Setup.exe"),
                 ("소문자 setup", "ChanceBlogDesktop-1.0.1-setup.exe"), ("숫자가 아닌 판", "ChanceBlogDesktop-1.0.x-Setup.exe"), ("rc 가 아닌 사전판", "ChanceBlogDesktop-1.0.1-beta.1-Setup.exe"),
                 ("빌드 표시", "ChanceBlogDesktop-1.0.1+7-Setup.exe"), ("앞에 붙은 글", "x" + SETUP_101), ("끝에 붙은 글", SETUP_101 + "x"), ("판 칸이 둘", "ChanceBlogDesktop-1.0.1-1.0.2-Setup.exe"),
                 ("rc 번호가 0", "ChanceBlogDesktop-1.0.1-rc.0-Setup.exe"), ("폴더 글만(이름이 비었다)", ""))
        with mock.patch.object(source, "_regular_size", side_effect=AssertionError("이름이 틀리면 파일 시스템을 보기 전에 거절해야 한다")):
            for label, name in names:
                for call in (apply.inno_command, apply.launch_setup):
                    with self.subTest(label=label, call=call.__name__):
                        error = self.refusal(call, folder + name, log)
                        self.assertEqual((error.code, error.detail), ("UPDATE_APPLY_FAILED", "setup_name"))
        self.assertEqual(self.popen.calls, [], "아무것도 띄우지 않았다")
        for name in (SETUP_101, "ChanceBlogDesktop-1.0.2-Setup.exe", "ChanceBlogDesktop-10.20.30-rc.12-Setup.exe"):         # 대조: 규칙 모양의 이름은 통과한다(규칙이 모든 것을 막는 것이 아니다)
            (setup.parent / name).write_bytes(b"not a real setup program")
            self.popen.calls.clear()
            apply.launch_setup(folder + name, log)
            self.assertEqual(len(self.popen.calls), 1, name)

    def test_a_network_or_device_path_is_refused_before_the_file_system_is_touched(self):
        """독립 검증 S R6 — 설치 도구는 이 PC 의 데이터 폴더 안에서만 띄운다: 네트워크(UNC)·장치 이름 공간 꼴은 이름이 규칙대로여도 거절한다(윈도 꼴 경로는 윈도에서만 절대 경로라 다른 운영체제는 '절대 경로가 아님' 으로 먼저 거절된다)."""
        setup, log = self.paths()
        windows_shapes = (("UNC", BS * 2 + "fileserver" + BS + "share" + BS + "run" + BS), ("확장 길이 접두어", BS * 2 + "?" + BS + "C:" + BS + "run" + BS), ("장치 이름 공간", BS * 2 + "." + BS + "C:" + BS + "run" + BS))
        any_shapes = (("슬래시 둘", "//fileserver/share/run/"), ("슬래시와 역슬래시", "/" + BS + "fileserver/share/run/"))
        with mock.patch.object(source, "_regular_size", side_effect=AssertionError("네트워크 꼴은 파일 시스템을 보기 전에 거절해야 한다")):
            for call in (apply.inno_command, apply.launch_setup):
                for label, prefix in any_shapes + windows_shapes:
                    with self.subTest(label=label, call=call.__name__):
                        wanted = "path_unc" if (os.name == "nt" or (label, prefix) in any_shapes) else "path_not_absolute"
                        self.assertEqual(self.refusal(call, prefix + SETUP_101, prefix + apply.UPDATE_LOG_NAME).detail, wanted)
                        self.assertEqual(self.refusal(call, setup, prefix + apply.UPDATE_LOG_NAME).detail, wanted, "로그만 네트워크 꼴이어도 같다")
                        self.assertEqual(self.refusal(call, prefix + SETUP_101, log).detail, wanted, "Setup 만 네트워크 꼴이어도 같다")
        self.assertEqual(self.popen.calls, [])

    def test_the_network_shape_is_exactly_two_leading_separators_and_never_blocks_an_ordinary_path(self):
        """네트워크·장치 꼴 판정 자체(독립 검증 S R6 의 방어 한 겹이 정상 경로를 막으면 업데이트가 영영 적용되지 않는다): 앞 두 글자가 **모두** 구분자일 때만 그렇다 — 구분자 하나로 시작하는 경로·드라이브 글자 경로는 아니다."""
        shapes = (("//x", True), (BS * 2 + "x", True), ("/" + BS + "x", True), (BS + "/x", True), (BS * 2 + "?" + BS + "C:", True), (BS * 2 + "." + BS + "C:", True),
                  ("/", False), ("/x", False), (BS + "x", False), (BS, False), ("", False), ("C:" + BS + "x", False), ("C:/x", False), ("x//y", False), ("a" + BS * 2 + "b", False), (" //x", False), ("/tmp/run/x", False))
        for text, expected in shapes:
            with self.subTest(text=text):
                self.assertIs(apply._is_network_or_device_path(text), expected)

    def test_a_log_name_that_only_looks_like_ours_is_refused(self):
        """독립 검증 Q R3(변이 Q27) — 고정 이름 둘(`setup-update.log`·`setup-recovery.log`) 말고는 가까운 이름도 안 된다: 접두어·확장자·대소문자·끝의 점/공백·`:` 스트림·앞뒤에 붙은 글."""
        setup, log = self.paths()
        folder = str(setup.parent) + os.sep
        for name in ("setup-evil.log", "setup-update.log.bak", "Setup-update.log", "SETUP-UPDATE.LOG", "setup-update.txt", "setup-.log", "setup-update.log.", "setup-update.log ", "setup-update.log:stream",
                     "setup-update.logx", "xsetup-update.log", "setup-recovery.log.bak", "setup-recovery.LOG", "setup-update.log.setup-recovery.log"):
            for call in (apply.inno_command, apply.launch_setup):
                with self.subTest(name=name, call=call.__name__):
                    self.assertEqual(self.refusal(call, setup, folder + name).detail, "log_path")
        self.assertEqual(self.popen.calls, [])
        for name in (apply.UPDATE_LOG_NAME, apply.RECOVERY_LOG_NAME):                 # 대조: 고정 이름 둘은 통과한다
            self.assertEqual(apply.inno_command(setup, folder + name)[-1], "/LOG=" + folder + name)


class SpawnOptionsTest(LaunchCase):
    def test_on_windows_the_child_is_detached_and_in_its_own_process_group_with_nothing_inherited(self):
        with mock.patch.object(apply, "IS_WINDOWS", True):
            options = apply.spawn_options()
        self.assertEqual(options, {"shell": False, "close_fds": True, "stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "creationflags": 0x00000008 | 0x00000200})
        self.assertEqual((apply.DETACHED_PROCESS, apply.CREATE_NEW_PROCESS_GROUP), (0x8, 0x200), "윈도 프로세스 생성 플래그의 공개된 값")
        self.assertEqual(options["creationflags"], apply.DETACHED_PROCESS | apply.CREATE_NEW_PROCESS_GROUP)
        if os.name == "nt":
            self.assertEqual(apply.DETACHED_PROCESS, subprocess.DETACHED_PROCESS, "이 파이썬의 윈도 상수와 같다")
            self.assertEqual(apply.CREATE_NEW_PROCESS_GROUP, subprocess.CREATE_NEW_PROCESS_GROUP)

    def test_elsewhere_the_child_starts_a_new_session_and_no_windows_flag_is_passed(self):
        with mock.patch.object(apply, "IS_WINDOWS", False):
            options = apply.spawn_options()
        self.assertEqual(options, {"shell": False, "close_fds": True, "stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "start_new_session": True})
        self.assertNotIn("creationflags", options, "윈도가 아닌 곳에서 creationflags 를 넘기면 파이썬이 거절한다")

    def test_nothing_is_piped_so_nothing_is_ever_read_and_no_shell_is_used(self):
        for flag in (True, False):
            with mock.patch.object(apply, "IS_WINDOWS", flag):
                options = apply.spawn_options()
            self.assertIs(options["shell"], False)
            for stream in ("stdin", "stdout", "stderr"):
                self.assertIs(options[stream], subprocess.DEVNULL, stream)
                self.assertIsNot(options[stream], subprocess.PIPE)
            self.assertIs(options["close_fds"], True)

    def test_the_default_follows_the_real_operating_system(self):
        self.assertEqual(apply.IS_WINDOWS, os.name == "nt")


class LaunchSetupTest(LaunchCase):
    def test_a_closed_switch_never_reaches_the_process_call(self):
        setup, log = self.paths()
        cap.switch_off("UPDATE_APPLY")
        error = self.refusal(apply.launch_setup, setup, log)
        self.assertEqual((error.code, error.slots), ("UPDATE_DISABLED", {"작업": "업데이트 설치 도구 띄우기"}))
        for value in (1, "yes", "True", [1]):
            with mock.patch("chanceblog_desktop.capabilities.UPDATE_APPLY", value):
                self.assertEqual(self.refusal(apply.launch_setup, setup, log).code, "UPDATE_DISABLED", repr(value))
        self.assertEqual(self.popen.calls, [], "꺼져 있으면 하위 프로세스를 한 번도 부르지 않는다")

    def test_exactly_one_process_call_with_the_fixed_command_and_the_detaching_options(self):
        setup, log = self.paths()
        for flag in (True, False):
            self.popen.calls.clear()
            with mock.patch.object(apply, "IS_WINDOWS", flag):
                self.assertIsNone(apply.launch_setup(setup, log))
                expected_options = apply.spawn_options()
            self.assertEqual(len(self.popen.calls), 1)
            command, options = self.popen.calls[0]
            self.assertEqual(command, [str(setup), *FIXED_ARGS, "/LOG=" + str(log)])
            self.assertEqual(options, expected_options)
            self.assertIs(options["shell"], False)

    def test_the_process_object_is_never_touched_and_the_trap_is_not_blind(self):
        with self.assertRaises(AssertionError):
            self.popen.process.returncode
        for name in ("pid", "poll", "wait", "communicate", "stdout", "stderr", "stdin"):
            with self.assertRaises(AssertionError, msg=name):
                getattr(self.popen.process, name)
        setup, log = self.paths()
        apply.launch_setup(setup, log)                       # 대역의 개체에 닿았다면 위의 함정이 터졌을 것이다
        self.assertEqual(len(self.popen.calls), 1)

    def test_a_launch_failure_becomes_apply_failed_with_one_reason_and_leaks_neither_path_nor_message(self):
        setup, log = self.paths("secret-place")
        canary = "CANARY_" + "WIN_ERROR_TEXT"
        for error in (OSError(13, canary + " C:\\Users\\Someone\\secret.exe"), PermissionError(canary), FileNotFoundError(canary), OSError(193, canary), ValueError("embedded null " + canary)):
            with self.subTest(error=type(error).__name__):
                self.popen.error = error
                raised = self.refusal(apply.launch_setup, setup, log)
                self.assertEqual((raised.code, raised.detail), ("UPDATE_APPLY_FAILED", "launch_failed"))
                shown = " ".join((str(raised), raised.detail, raised.log_line(), repr(raised.slots), raised.rendered().message, raised.rendered().action))
                for secret in (canary, "Someone", "secret", str(self.tmp), SETUP_101):
                    self.assertNotIn(secret, shown, secret)
                self.assertTrue(raised.__suppress_context__, "원래 오류의 글이 추적에 따라 나오지 않는다")
                self.assertIsNone(raised.__cause__, "원래 오류를 `from 오류` 로 이어 붙이지 않는다(독립 검증 Q R2 — `__suppress_context__` 는 `from 오류` 에서도 참이라 이것만으로는 모자라다)")
                printed = "".join(traceback.format_exception(type(raised), raised, raised.__traceback__))
                for secret in (canary, "Someone", "secret"):
                    self.assertNotIn(secret, printed, "추적을 찍어도 윈도 오류 글·경로가 따라 나오지 않는다: " + secret)

    def test_an_unexpected_error_is_not_swallowed_and_reaches_the_caller_as_it_is(self):
        setup, log = self.paths()
        for error in (RuntimeError("boom"), AssertionError("x"), KeyboardInterrupt()):
            self.popen.error = error
            with self.assertRaises(type(error)):
                apply.launch_setup(setup, log)

    def test_unsafe_paths_never_reach_the_process_call(self):
        setup, log = self.paths()
        for one, two in ((SETUP_101, log), (setup, setup.parent / "evil.log"), (self.tmp / "missing.exe", self.tmp / apply.UPDATE_LOG_NAME)):
            self.assertEqual(self.refusal(apply.launch_setup, one, two).code, "UPDATE_APPLY_FAILED")
        self.assertEqual(self.popen.calls, [])


class InnoAdapterTest(LaunchCase):
    def adapter(self):
        return apply.adapter_for("inno")

    def go(self, staged, **overrides):
        options = dict(from_version="1.0.0", to_version="1.0.1", recovery=False)
        options.update(overrides)
        return self.adapter().apply(staged, **options)

    def test_a_verified_setup_is_launched_once_with_the_update_log_beside_it(self):
        staged = make_staged(self.tmp)
        self.assertIs(self.go(staged), True)
        self.assertEqual(len(self.popen.calls), 1)
        command, options = self.popen.calls[0]
        self.assertEqual(command, [str(staged.files["setup"]), *FIXED_ARGS, "/LOG=" + str(staged.folder / "setup-update.log")])
        self.assertEqual(options, apply.spawn_options())
        self.assertEqual(sorted(path.name for path in staged.folder.iterdir()), [SETUP_101], "어댑터는 폴더에 아무것도 만들지 않는다(로그는 Setup 이 쓴다)")

    def test_a_setup_changed_after_the_check_is_refused_by_the_last_second_hash_and_nothing_starts(self):
        staged = make_staged(self.tmp)
        path = staged.files["setup"]
        path.write_bytes(path.read_bytes()[:-1] + b"X")
        error = self.refusal(self.go, staged)
        self.assertEqual((error.code, error.detail), ("UPDATE_SIGNATURE_INVALID", "restage:setup"))
        path.unlink()
        self.assertEqual(self.refusal(self.go, staged).code, "UPDATE_SIGNATURE_INVALID", "사라진 파일도 같다")
        self.assertEqual(self.popen.calls, [])

    def test_a_set_without_the_setup_role_is_refused_although_the_hash_check_alone_passes_it_vacuously(self):
        staged = make_staged(self.tmp)
        empty = source.StagedUpdate(staged.folder, {}, staged.manifest)
        self.assertTrue(source.verify_staged(empty), "받은 파일이 하나도 없으면 재해시는 확인할 것이 없어 통과한다 — 그래서 어댑터가 따로 역할을 요구한다")
        self.assertEqual(self.refusal(self.go, empty).detail, "setup_missing")
        thin = dataclasses.replace(staged.manifest, files=tuple(item for item in staged.manifest.files if item.role != "setup"))
        self.assertEqual(self.refusal(self.go, source.StagedUpdate(staged.folder, staged.files, thin)).detail, "setup_missing")
        self.assertEqual(self.popen.calls, [])

    def test_a_setup_outside_the_staging_folder_or_with_another_name_is_refused(self):
        staged = make_staged(self.tmp)
        other = make_staged(self.tmp, folder_name="somewhere-else")
        moved = source.StagedUpdate(staged.folder, {"setup": other.files["setup"]}, staged.manifest)
        self.assertEqual(self.refusal(self.go, moved).detail, "setup_path", "받은 폴더 밖의 같은 이름 파일")
        entry = staged.manifest.file("setup")
        for label, name in (("다른 이름", "evil.exe"), ("버전 없는 이름", "ChanceBlogDesktop-Setup.exe"), ("확장자", "ChanceBlogDesktop-1.0.1-Setup.cmd"), ("경로 구분자", "x/ChanceBlogDesktop-1.0.1-Setup.exe")):
            with self.subTest(label=label):
                renamed = dataclasses.replace(staged.manifest, files=tuple(dataclasses.replace(entry, name=name) if item.role == "setup" else item for item in staged.manifest.files))
                self.assertEqual(self.refusal(self.go, source.StagedUpdate(staged.folder, staged.files, renamed)).detail, "setup_path")
        self.assertEqual(self.popen.calls, [])

    def test_a_setup_whose_own_name_breaks_the_naming_rule_is_refused_even_when_the_file_and_the_manifest_agree(self):
        """변이로 찾은 틈 — 위 시험은 매니페스트 쪽 이름만 바꿔 '파일 이름 ≠ 매니페스트 이름' 이 먼저 걸렸다. 여기서는 파일 이름도 같이 바꿔(파일·매니페스트·크기·해시가 모두 서로 맞다) **이름 규칙만이** 막게 한다."""
        staged = make_staged(self.tmp)
        entry = staged.manifest.file("setup")
        original = staged.files["setup"].read_bytes()
        for label, name in (("다른 이름", "evil.exe"), ("스크립트", "ChanceBlogDesktop-1.0.1-Setup.cmd"), ("버전 없는 이름", "ChanceBlogDesktop-Setup.exe"), ("바깥 글자", "ChanceBlogDesktop-1.0.1-Setup.exe.exe")):
            with self.subTest(label=label):
                renamed_file = staged.folder / name
                renamed_file.write_bytes(original)
                renamed = dataclasses.replace(staged.manifest, files=tuple(dataclasses.replace(entry, name=name) if item.role == "setup" else item for item in staged.manifest.files))
                bent = source.StagedUpdate(staged.folder, {"setup": renamed_file}, renamed)
                self.assertTrue(source.verify_staged(bent), "크기와 해시가 맞다 — 이름 규칙만이 막는다")
                self.assertEqual(self.refusal(self.go, bent).detail, "setup_path")
        self.assertEqual(self.popen.calls, [])

    def test_the_version_must_match_and_an_update_must_go_up_while_a_recovery_must_go_down(self):
        staged = make_staged(self.tmp)
        self.assertIs(self.go(staged), True)
        for label, overrides, reason in (("같은 버전으로 올림", dict(from_version="1.0.1"), "direction"), ("높은 판에서 낮은 판으로", dict(from_version="1.0.2"), "direction"),
                                         ("매니페스트와 다른 버전", dict(to_version="1.0.2"), "version_mismatch"), ("읽을 수 없는 이전 버전", dict(from_version="x"), "version_invalid"),
                                         ("복구인데 올림", dict(from_version="1.0.0", recovery=True), "direction"), ("복구인데 같은 버전", dict(from_version="1.0.1", recovery=True), "direction")):
            with self.subTest(label=label):
                before = len(self.popen.calls)
                self.assertEqual(self.refusal(self.go, staged, **overrides).detail, reason)
                self.assertEqual(len(self.popen.calls), before)
        older = make_staged(self.tmp, older_release(), folder_name="kept-1.0.0")
        self.assertIs(self.go(older, from_version="1.0.1", to_version="1.0.0", recovery=True), True)
        self.assertEqual(self.refusal(self.go, older, from_version="1.0.1", to_version="1.0.0", recovery=False).detail, "direction", "낮은 판을 복구 표시 없이 설치하지 않는다")

    def test_a_manifest_of_another_installer_kind_is_refused_by_name(self):
        staged = make_staged(self.tmp, fs.Release("1.0.1", kind="velopack"))
        self.assertEqual(self.refusal(self.go, staged).detail, "kind_mismatch")
        self.assertEqual(self.popen.calls, [])

    def test_a_multi_chunk_file_is_hashed_to_the_end_by_the_last_second_check(self):
        """독립 검증 Q R1(변이 Q20) — 띄우기 직전 재해시가 큰 파일을 덩어리마다 끝까지 읽는다. 실제 Setup 은 수십 MB 라 덩어리(1 MiB)를 여러 번 도는데 시험의 가짜 Setup 은 3000바이트라 한 번만 돌아, 해시가 첫 덩어리만 읽는 틀린 코드가 살아남았다 —
        `source.CHUNK` 를 64 로 줄여 작은 파일로 여러 덩어리를 돌고 마지막 바이트 하나만 바꿔도 `restage:setup` 으로 걸리게 한다(틀린 코드는 정상 파일부터 거절하거나 바뀐 파일을 통과시킨다)."""
        staged = make_staged(self.tmp)
        path = staged.files["setup"]
        with mock.patch.object(source, "CHUNK", 64):
            self.assertTrue(source.verify_staged(staged), "손대지 않은 파일은 작은 덩어리로 여러 번 읽어도 서명된 값과 같다")
            self.assertIs(self.go(staged), True)
            self.popen.calls.clear()
            original = path.read_bytes()
            self.assertGreater(len(original), 64 * 4, "여러 덩어리가 되는 크기다")
            path.write_bytes(original[:-1] + bytes([original[-1] ^ 1]))
            error = self.refusal(self.go, staged)
            self.assertEqual((error.code, error.detail), ("UPDATE_SIGNATURE_INVALID", "restage:setup"))
        self.assertEqual(self.popen.calls, [])

    def test_a_kept_older_setup_changed_after_it_was_kept_is_refused_by_the_last_second_hash_in_a_recovery_too(self):
        """독립 검증 S I2(변이 S06) — D-851 ③ 은 '복구 경로 포함' 이라고 적는다. 복구일 때만 띄우기 직전 재해시를 건너뛰어도 흐름의 보관본 확인이 대신 막아 시험이 그 차이를 못 봤다 — 복구 표시로 변조한 보관본을 어댑터에 직접 넣어 못박는다."""
        older = make_staged(self.tmp, older_release(), folder_name="keep-1.0.0")
        path = older.files["setup"]
        path.write_bytes(path.read_bytes()[:-1] + b"X")
        error = self.refusal(self.go, older, from_version="1.0.1", to_version="1.0.0", recovery=True)
        self.assertEqual((error.code, error.detail), ("UPDATE_SIGNATURE_INVALID", "restage:setup"))
        path.unlink()
        self.assertEqual(self.refusal(self.go, older, from_version="1.0.1", to_version="1.0.0", recovery=True).detail, "restage:setup", "사라진 보관본도 같다")
        self.assertEqual(self.popen.calls, [])

    def test_a_version_slot_that_only_looks_like_a_version_is_refused_even_when_name_manifest_file_and_target_all_agree(self):
        """독립 검증 S I2(변이 S10) — 이름 규칙(`SETUP_NAME`)의 판 칸을 아무 글자나 되게 느슨하게 해도 매니페스트의 이름 규칙이 같은 일을 해서 시험이 못 봤다. 여기서는 파일·매니페스트·크기·해시·`to_version` 이 모두 서로 맞고(어댑터의 다른 검사는 다 통과)
        **이름 규칙만이** 막게 한다 — 판 칸은 숫자 셋과 `-rc.번호` 뿐이다."""
        staged = make_staged(self.tmp)
        entry = staged.manifest.file("setup")
        original = staged.files["setup"].read_bytes()
        for label, version in (("rc 가 아닌 사전판", "1.0.1-beta.2"), ("빌드 표시", "1.0.1+7"), ("사전판과 빌드 표시", "1.0.1-rc.1+7")):
            with self.subTest(label=label):
                name = f"ChanceBlogDesktop-{version}-Setup.exe"
                (staged.folder / name).write_bytes(original)
                bent_manifest = dataclasses.replace(staged.manifest, version=version, files=tuple(dataclasses.replace(entry, name=name) if item.role == "setup" else item for item in staged.manifest.files))
                bent = source.StagedUpdate(staged.folder, {"setup": staged.folder / name}, bent_manifest)
                self.assertTrue(source.verify_staged(bent), "크기와 해시가 맞다 — 이름 규칙만이 막는다")
                error = self.refusal(self.go, bent, to_version=version)
                self.assertEqual((error.code, error.detail), ("UPDATE_APPLY_FAILED", "setup_path"))
        self.assertEqual(self.popen.calls, [])

    def test_a_pre_release_manifest_is_not_the_stable_version_it_is_called_for(self):
        """독립 검증 Q R3(변이 Q25) — 사전판 꼬리가 달라도 같은 판이 아니다: `1.0.1-rc.1` 매니페스트를 `to_version=1.0.1` 로 부르면 거절한다. 시험이 먼 값(`1.0.2`)만 쓰면 '꼬리를 무시하는' 틀린 코드가 살아남는다."""
        candidate = fs.Release("1.0.1-rc.1", channel="rc")
        verified = manifest_module.read_and_verify(candidate.manifest_bytes, candidate.signature, keyring=fs.RING, channels=manifest_module.CHANNELS_OFFLINE)
        folder = self.tmp / "rc-run"
        folder.mkdir()
        name = "ChanceBlogDesktop-1.0.1-rc.1-Setup.exe"
        (folder / name).write_bytes(candidate.bodies[name])
        staged = source.StagedUpdate(folder, {"setup": folder / name}, verified)
        self.assertIs(self.go(staged, to_version="1.0.1-rc.1"), True, "맞는 사전판 번호는 통과한다")
        self.popen.calls.clear()
        for wrong in ("1.0.1", "1.0.1-rc.2", "1.0.1-rc.10", "1.0.1-rc.1+7", "1.0.0"):
            with self.subTest(to_version=wrong):
                self.assertEqual(self.refusal(self.go, staged, to_version=wrong).detail, "version_mismatch")
        stable = make_staged(self.tmp, folder_name="stable-run")
        for wrong in ("1.0.1-rc.1", "1.0.1+7"):
            with self.subTest(stable_called_as=wrong):
                self.assertEqual(self.refusal(self.go, stable, to_version=wrong).detail, "version_mismatch")
        self.assertEqual(self.popen.calls, [])

    def test_a_setup_named_for_another_version_than_the_manifest_is_refused_even_when_everything_else_agrees(self):
        """독립 검증 Q R3 — 매니페스트가 `1.0.1` 인데 파일·크기·해시가 맞는 `ChanceBlogDesktop-9.9.9-Setup.exe` 를 `StagedUpdate` 로 직접 만들어 넘기면 예전에는 띄웠다(흐름으로는 닿지 않지만 방어를 겹으로 둔다)."""
        staged = make_staged(self.tmp)
        entry = staged.manifest.file("setup")
        original = staged.files["setup"].read_bytes()
        for version in ("9.9.9", "1.0.2", "1.0.0", "1.0.1-rc.1", "10.0.1"):
            with self.subTest(file_name_version=version):
                name = f"ChanceBlogDesktop-{version}-Setup.exe"
                (staged.folder / name).write_bytes(original)
                bent_manifest = dataclasses.replace(staged.manifest, files=tuple(dataclasses.replace(entry, name=name) if item.role == "setup" else item for item in staged.manifest.files))
                bent = source.StagedUpdate(staged.folder, {"setup": staged.folder / name}, bent_manifest)
                self.assertTrue(source.verify_staged(bent), "파일·크기·해시가 맞다 — 이름 속 판만 다르다")
                error = self.refusal(self.go, bent)
                self.assertEqual((error.code, error.detail), ("UPDATE_APPLY_FAILED", "setup_version"))
        self.assertEqual(self.popen.calls, [])

    def test_the_path_text_check_accepts_only_non_empty_text_without_a_null_character(self):
        for value, expected in (("a", True), (Path("a"), True), ("a b", True), ("", False), ("a" + chr(0), False), (5, False), (b"a", False), (None, False), (["a"], False), (object(), False)):
            with self.subTest(value=repr(value)[:30]):
                self.assertIs(apply._is_path_text(value), expected)

    def test_a_received_folder_shaped_like_a_network_path_is_refused_by_the_adapter_check_before_anything_starts(self):
        """데이터 폴더를 네트워크(UNC) 경로에 둔 사용자의 업데이트는 `launch_setup` 이 어차피 거절한다 — 어댑터의 마지막 검사(흐름이 백업 앞에서도 부른다)가 같은 이유(`path_unc`)로 먼저 막아 쓸데없는 전체 백업을 만들지 않는다. 글자만 보는 검사라 네트워크에 닿지 않는다."""
        staged = make_staged(self.tmp)
        name = staged.manifest.file("setup").name
        for label, folder in (("슬래시 둘", "//fileserver/share/run"), ("슬래시와 역슬래시", "/" + BS + "fileserver/share/run"), ("역슬래시 둘 UNC", BS * 2 + "fileserver" + BS + "share" + BS + "run"),
                              ("확장 길이 접두어", BS * 2 + "?" + BS + "C:" + BS + "run")):
            with self.subTest(label=label):
                bent = source.StagedUpdate(folder, {"setup": folder + "/" + name}, staged.manifest)
                with mock.patch.object(source, "verify_staged", side_effect=AssertionError("네트워크 꼴이면 재해시(파일 시스템·네트워크)까지 가면 안 된다")):
                    error = self.refusal(self.go, bent)
                self.assertEqual((error.code, error.detail), ("UPDATE_APPLY_FAILED", "path_unc"))
        self.assertEqual(self.popen.calls, [])

    def test_a_path_like_value_that_gives_bytes_is_refused_without_an_exception(self):
        """`PathLike` 인데 `__fspath__` 가 글이 아니라 바이트를 내거나(`os.fspath` 는 통과, `str` 이 아님) 숫자를 내는(`os.fspath` 가 `TypeError`) 값도 생 예외 대신 같은 거절이다 — 흐름이 백업 앞에서 같은 함수를 부르므로 생 예외는 더 앞에서 샌다."""
        class GivesBytes:
            def __init__(self, text):
                self.text = text

            def __fspath__(self):
                return self.text.encode("utf-8")

        class GivesNumber:
            def __fspath__(self):
                return 5
        staged = make_staged(self.tmp)
        here = str(staged.files["setup"])
        for label, files, folder, reason in (("Setup 값", {"setup": GivesBytes(here)}, staged.folder, "setup_path"), ("다른 역할의 값", {**staged.files, "package": GivesBytes(here)}, staged.folder, "staged_invalid"),
                                             ("받은 폴더", staged.files, GivesBytes(str(staged.folder)), "setup_path"),
                                             ("Setup 값(숫자를 내는 PathLike)", {"setup": GivesNumber()}, staged.folder, "setup_path"), ("다른 역할의 값(숫자를 내는 PathLike)", {**staged.files, "package": GivesNumber()}, staged.folder, "staged_invalid"),
                                             ("받은 폴더(숫자를 내는 PathLike)", staged.files, GivesNumber(), "setup_path")):
            with self.subTest(label=label):
                error = self.refusal(self.go, source.StagedUpdate(folder, files, staged.manifest))
                self.assertEqual((error.code, error.detail), ("UPDATE_APPLY_FAILED", reason))
        self.assertEqual(self.popen.calls, [])

    def test_the_other_roles_the_rehash_will_read_must_be_path_text_too(self):
        """재해시(`verify_staged`)는 매니페스트의 모든 역할을 읽는다 — Setup 말고 다른 역할의 값이 경로 글이 아니면 거기서 생 예외가 나므로 어댑터가 미리 `staged_invalid` 로 거절한다(널 문자·숫자·바이트·빈 글)."""
        staged = make_staged(self.tmp)
        roles = [item.role for item in staged.manifest.files if item.role != "setup"]
        self.assertTrue(roles, "가짜 릴리스의 매니페스트에는 Setup 말고도 역할이 있다")
        for role in roles:
            for label, odd in (("숫자", 5), ("바이트", b"x"), ("널 문자", "a" + chr(0) + "b"), ("빈 글", ""), ("목록", ["x"])):
                with self.subTest(role=role, value=label):
                    error = self.refusal(self.go, source.StagedUpdate(staged.folder, {**staged.files, role: odd}, staged.manifest))
                    self.assertEqual((error.code, error.detail), ("UPDATE_APPLY_FAILED", "staged_invalid"))
        self.assertEqual(self.popen.calls, [])

    def test_a_recovery_starts_the_kept_older_setup_the_same_way_with_its_own_log_name(self):
        older = make_staged(self.tmp, older_release(), folder_name="keep-1.0.0")
        self.assertIs(self.go(older, from_version="1.0.1", to_version="1.0.0", recovery=True), True)
        command, options = self.popen.calls[0]
        self.assertEqual(command, [str(older.files["setup"]), *FIXED_ARGS, "/LOG=" + str(older.folder / "setup-recovery.log")])
        self.assertEqual(options, apply.spawn_options())
        newer = make_staged(self.tmp, folder_name="staging-1.0.1")
        self.go(newer)
        self.assertNotEqual(self.popen.calls[0][0][-1].rsplit(os.sep, 1)[-1], self.popen.calls[1][0][-1].rsplit(os.sep, 1)[-1], "업데이트와 복구는 서로의 로그를 덮어쓰지 않는다")
        self.assertEqual(self.popen.calls[1][0][-1], "/LOG=" + str(newer.folder / "setup-update.log"))

    def test_every_malformed_staged_value_closes_to_apply_failed_without_an_exception(self):
        good = make_staged(self.tmp)
        cases = (None, object(), {}, [], "x", 5, SimpleNamespace(files={}, manifest=good.manifest, folder=good.folder), source.StagedUpdate(good.folder, None, good.manifest),
                 source.StagedUpdate(good.folder, {}, None), source.StagedUpdate(good.folder, {}, object()), source.StagedUpdate(good.folder, [], good.manifest),
                 source.StagedUpdate(None, good.files, good.manifest), source.StagedUpdate(5, good.files, good.manifest), source.StagedUpdate(b"folder", good.files, good.manifest))
        for staged in cases:
            with self.subTest(staged=type(staged).__name__):
                error = self.refusal(self.go, staged)
                self.assertEqual((error.code, error.detail), ("UPDATE_APPLY_FAILED", "staged_invalid"))
        for label, odd in (("숫자", 5), ("바이트", b"setup.exe"), ("목록", ["setup.exe"])):
            with self.subTest(setup_value=label):
                error = self.refusal(self.go, source.StagedUpdate(good.folder, {"setup": odd}, good.manifest))
                self.assertEqual((error.code, error.detail), ("UPDATE_APPLY_FAILED", "setup_path"))
        self.assertEqual(self.popen.calls, [])

    def test_the_switch_gate_comes_first_even_for_garbage_input(self):
        cap.switch_off("UPDATE_APPLY")
        for staged in (None, make_staged(self.tmp)):
            self.assertEqual(self.refusal(self.go, staged).code, "UPDATE_DISABLED")
        self.assertEqual(self.popen.calls, [])

    def test_a_launch_failure_through_the_adapter_is_the_apply_failure_without_a_cause_text(self):
        staged = make_staged(self.tmp)
        self.popen.error = OSError(2, "CANARY_" + "NOT_FOUND C:\\Users\\Someone")
        error = self.refusal(self.go, staged)
        self.assertEqual((error.code, error.detail), ("UPDATE_APPLY_FAILED", "launch_failed"))
        self.assertNotIn("Someone", error.log_line())


class ReadOnlyVelopackTest(unittest.TestCase):
    """`velopack` 은 매니페스트가 이름으로 부를 수 있지만(읽기) 어떤 설치 종류에서도 적용되지 않는다 — 안전하다는 근거(결정 D-850)를 시험이 지킨다."""

    def setUp(self):
        self.release = fs.Release("1.0.1", kind="velopack")
        self.manifest = manifest_module.read_and_verify(self.release.manifest_bytes, self.release.signature, keyring=fs.RING)

    def evaluate(self, install_kind):
        return manifest_module.evaluate(self.manifest, now=fs.NOW, current_version="1.0.0", install_kind=install_kind)

    def test_the_manifest_is_still_read_and_the_signature_is_still_required(self):
        self.assertEqual(self.manifest.installer_kind, "velopack")
        self.assertIn("velopack", manifest_module.INSTALLER_KINDS)
        stranger = fs.Release("1.0.1", kind="velopack", seed=us.seed_for("stranger"))
        with self.assertRaises(AppError) as caught:
            manifest_module.read_and_verify(stranger.manifest_bytes, stranger.signature, keyring=fs.RING)
        self.assertEqual(caught.exception.code, "UPDATE_SIGNATURE_INVALID")
        with self.assertRaises(AppError) as caught:
            manifest_module.read_and_verify(self.release.manifest_bytes, self.release.signature, keyring=keys.shipped_keyring())
        self.assertEqual(caught.exception.code, "UPDATE_SIGNATURE_INVALID", "출하 키가 비어 있는 동안은 서명이 어떤 판이든 모두 거절된다")

    def test_an_inno_app_is_told_to_install_by_hand_and_no_detectable_kind_can_apply_it(self):
        with self.assertRaises(AppError) as caught:
            self.evaluate("inno")
        self.assertEqual((caught.exception.code, caught.exception.detail), ("UPDATE_NEEDS_MANUAL_INSTALL", "manifest:installer_kind"))
        for kind in ("portable", "source", ""):
            verdict = self.evaluate(kind)
            self.assertEqual((verdict.status, verdict.apply_possible), ("AVAILABLE", False), kind)
        from chanceblog_desktop.update import install_kind
        for present in ((), ("unins000.exe",), ("Update.exe", "sq.version"), ("Update.exe", "sq.version", "unins000.exe")):
            detected = install_kind.detect("C:/app", frozen=True, exists=lambda path: Path(path).name in present)
            self.assertNotEqual(detected, "velopack")
            if detected == "inno":
                with self.assertRaises(AppError):
                    self.evaluate(detected)
            else:
                self.assertFalse(self.evaluate(detected).apply_possible)

    def test_a_velopack_release_is_refused_before_any_download_copy_or_backup_whatever_the_check_claims(self):
        holder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(holder.cleanup)
        ctx = fs.make_world(Path(holder.name))
        folder = update_flow.update_folder(ctx)
        claimed = update_flow.CheckResult("AVAILABLE", self.manifest, True, "1.0.0", self.release.manifest_bytes, self.release.signature, "folder", str(Path(holder.name) / "picked"))
        online = dataclasses.replace(claimed, source="online", folder="")
        staged = source.StagedUpdate(Path(holder.name) / "nothing", {}, self.manifest)
        with fs.switches_on("NET_UPDATE_CHECK", "UPDATE_APPLY"):
            for label, call in (("받기", lambda: update_flow.download_update(ctx, online)), ("폴더에서 복사", lambda: update_flow.stage_update_from_folder(ctx, claimed)),
                                ("적용", lambda: update_flow.apply_update(ctx, online, staged, confirmed=True))):
                with self.subTest(label=label):
                    with self.assertRaises(AppError) as caught:
                        call()
                    self.assertEqual((caught.exception.code, caught.exception.detail), ("UPDATE_APPLY_FAILED", "kind_not_supported"))
        self.assertFalse(folder.exists(), "아무것도 만들지 않았다(백업·상태 파일·임시 폴더 0)")
        self.assertEqual(list(ctx.workspace.root.glob("backups")), [])

    def test_the_stored_pending_kind_still_reads_so_an_old_state_file_is_not_thrown_away(self):
        """상태 파일의 `pending.kind` 는 `velopack` 도 읽는다(실제로 그런 파일이 생긴 적은 없다) — 읽는 것은 분류일 뿐이고 복구에서 쓰려 하면 어댑터가 거절한다."""
        self.assertEqual(state.KINDS, ("velopack", "inno"))
        pending = state.Pending("1.0.0", "1.0.1", 20261201030000, "full-20261201-040000", "2026-12-01T04:00:00Z", 0, "velopack")
        parsed = state.parse_state(json.dumps(state.state_to_dict(state.State(pending=pending))).encode("utf-8"))
        self.assertEqual(parsed.pending.kind, "velopack")
        with self.assertRaises(AppError) as caught:
            with fs.switches_on("UPDATE_APPLY"):
                apply.adapter_for(parsed.pending.kind).apply(None, from_version="1.0.1", to_version="1.0.0", recovery=True)
        self.assertEqual((caught.exception.code, caught.exception.detail), ("UPDATE_APPLY_FAILED", "kind_not_supported"))


class HandOffFlowTest(tf.FlowCase):
    """상태 기계 연결(지시서 5) — 진짜 `InnoAdapter` 를 어댑터 자리에 두고(주입 0) `subprocess.Popen` 만 대역으로 바꾼다: 적용 → `HANDED_OFF` → 앱 종료 → 다음 시작의 `note_boot`.
    앱이 먼저 끝나므로 Setup 의 종료 코드를 볼 수 없다는 설계 가정 — Setup 의 실패는 다음 시작의 시작 점검(적용되지 않았어요·연속 두 번 정상 표식 없음 → 복구 안내)이 잡는다."""
    switches = ("NET_UPDATE_CHECK", "UPDATE_APPLY")

    def session(self, **kwargs):
        options = dict(install_kind="inno", current_version="1.0.0", keyring=fs.RING)
        options.update(kwargs)
        return update_flow.UpdateSession(self.ctx, **options)

    def hand_off(self, popen, **kwargs):
        with mock.patch.object(subprocess, "Popen", popen):
            session = self.session(**kwargs)
            session.check()
            staged = session.download()
            result = session.apply(confirmed=True)
        return session, staged, result

    def test_a_whole_update_ends_in_handed_off_with_the_detached_launcher_and_without_waiting_for_the_setup(self):
        popen = FakePopen()
        session, staged, result = self.hand_off(popen)
        self.assertEqual((session.state, result.handed_off), ("HANDED_OFF", True))
        self.assertEqual(len(popen.calls), 1, "설치 도구는 정확히 한 번 띄웠다")
        command, options = popen.calls[0]
        self.assertEqual(command, [str(staged.files["setup"]), *FIXED_ARGS, "/LOG=" + str(staged.folder / "setup-update.log")])
        self.assertEqual(options, apply.spawn_options())
        after = self.state()
        self.assertEqual((after.pending.from_version, after.pending.to_version, after.pending.kind, after.pending.boot_attempts, after.pending.backup_name, after.last_seq),
                         ("1.0.0", "1.0.1", "inno", 0, result.backup_name, self.release.dict["seq"]), "넘기기 전에 표식이 적혔고 넘긴 순간 시퀀스가 올랐다")
        self.assertTrue(staged.files["setup"].is_file(), "받은 Setup 은 지워지지 않았다(Setup 이 읽는 중이다)")
        self.assertEqual(machine.allowed_events("HANDED_OFF"), (), "HANDED_OFF 는 끝점이다 — 앱은 곧 정상 종료한다")
        with self.assertRaises(machine.IllegalTransition):
            session.cancel()

    def test_when_the_setup_silently_did_nothing_the_next_start_of_the_old_version_reports_it(self):
        popen = FakePopen()
        session, staged, result = self.hand_off(popen)
        note = state.note_boot(version="1.0.0", folder=self.folder)
        self.assertEqual(note.action, "not_applied")
        after = self.state()
        self.assertEqual((after.pending, after.notice), (None, "not_applied"))
        fresh = self.session()
        self.assertEqual(fresh.on_boot(note), "IDLE")
        self.assertTrue(staged.folder.is_dir(), "받아 둔 폴더는 낡을 때까지 남는다(로그를 사람이 볼 수 있다)")

    def test_when_the_new_version_never_becomes_healthy_the_third_start_offers_the_recovery_which_starts_the_kept_older_setup(self):
        previous = older_release()
        keep = health.keep_dir(self.folder, "1.0.0")
        keep.mkdir(parents=True)
        (keep / "update-manifest.json").write_bytes(previous.manifest_bytes)
        (keep / "update-manifest.json.sig").write_bytes(previous.signature)
        (keep / SETUP_100).write_bytes(previous.bodies[SETUP_100])
        popen = FakePopen()
        self.hand_off(popen)
        actions = [state.note_boot(version="1.0.1", folder=self.folder) for _ in range(3)]
        self.assertEqual([note.action for note in actions], ["first_boot", "first_boot", "recovery_offered"])
        pending = self.state().pending
        fresh = self.session(current_version="1.0.1")
        self.assertEqual(fresh.on_boot(actions[-1]), "RECOVERY_OFFERED")
        restores = []
        with mock.patch.object(subprocess, "Popen", popen), mock.patch.object(backup_flow, "restore_full_backup", lambda ctx, name, *, confirmed, step=None: restores.append((name, confirmed))):
            outcome = fresh.recover(confirmed=True)
        self.assertEqual((fresh.state, outcome.steps), ("ROLLED_BACK", ("lock", "data", "installer", "apply", "record")))
        self.assertEqual(restores, [(pending.backup_name, True)])
        self.assertEqual(len(popen.calls), 2, "업데이트 한 번 + 복구 한 번")
        command, options = popen.calls[1]
        self.assertEqual(command, [str(keep / SETUP_100), *FIXED_ARGS, "/LOG=" + str(keep / "setup-recovery.log")])
        self.assertEqual(options, apply.spawn_options())
        launched = self.state()
        self.assertEqual((launched.pending, launched.notice, launched.last_good), (pending, "rollback_launched", ""), "이전 판 Setup 을 '띄웠다' 까지만 기록한다 — 표식은 그대로이고 정상 판 기록도 아직이다(독립 검증 S R4)")
        self.assertEqual(launched.last_seq, self.release.dict["seq"], "시퀀스는 복구가 건드리지 않는다")
        note = state.note_boot(version="1.0.0", folder=self.folder)                      # 이전 판이 실제로 켜졌다 — 그때 확정한다
        self.assertEqual((note.action, note.pending), ("rolled_back", None))
        after = self.state()
        self.assertEqual((after.pending, after.notice, after.last_good), (None, "rolled_back", "1.0.0"))
        self.assertEqual(after.last_seq, self.release.dict["seq"])
        self.assertEqual(state.note_boot(version="1.0.0", folder=self.folder).action, "none", "확정은 한 번뿐이다")
        self.assertEqual(self.session(current_version="1.0.0").on_boot(note), "IDLE", "확정 알림은 상태 기계를 움직이지 않는다(안내는 상태 파일의 `rolled_back`)")

    def keep_older_setup(self, kind="inno"):
        previous = older_release(kind)
        keep = health.keep_dir(self.folder, "1.0.0")
        keep.mkdir(parents=True)
        (keep / "update-manifest.json").write_bytes(previous.manifest_bytes)
        (keep / "update-manifest.json.sig").write_bytes(previous.signature)
        (keep / SETUP_100).write_bytes(previous.bodies[SETUP_100])
        return keep

    def offered_recovery(self, popen):
        """업데이트를 넘기고 새 판이 정상 표식 없이 세 번 켜져 복구 안내가 뜬 순간 → (복구 안내를 받은 세션, 그때의 표식)."""
        self.hand_off(popen)
        notes = [state.note_boot(version="1.0.1", folder=self.folder) for _ in range(3)]
        self.assertEqual([note.action for note in notes], ["first_boot", "first_boot", "recovery_offered"])
        pending = self.state().pending
        fresh = self.session(current_version="1.0.1")
        self.assertEqual(fresh.on_boot(notes[-1]), "RECOVERY_OFFERED")
        return fresh, pending

    def press_recover(self, session, popen):
        restores = []
        with mock.patch.object(subprocess, "Popen", popen), mock.patch.object(backup_flow, "restore_full_backup", lambda ctx, name, *, confirmed, step=None: restores.append((name, confirmed))):
            outcome = session.recover(confirmed=True)
        return outcome, restores

    def test_when_the_recovery_setup_silently_did_nothing_the_next_start_of_the_new_version_offers_the_recovery_again(self):
        """독립 검증 S R4 — 예전에는 복구 Setup 을 띄운 직후 표식을 지우고 '되돌렸다' 로 적어, 이전 Setup 이 조용히 안 돌아 새 판이 그대로 켜져도 다음 시작이 아무것도 몰랐다
        (상태는 '되돌렸다'·정상 판 1.0.0, 실제로 도는 판은 1.0.1, '연속 두 번 정상 표식 없음' 도 이미 지워진 뒤였다)."""
        keep = self.keep_older_setup()
        popen = FakePopen()
        fresh, pending = self.offered_recovery(popen)
        _outcome, restores = self.press_recover(fresh, popen)
        self.assertEqual((fresh.state, len(popen.calls), restores), ("ROLLED_BACK", 2, [(pending.backup_name, True)]))
        self.assertEqual(popen.calls[1][0][-1], "/LOG=" + str(keep / "setup-recovery.log"))
        before = (self.folder / "state.json").read_bytes()                                # 이전 Setup 이 조용히 안 돌았다 — 새 판(1.0.1)이 그대로 다시 켜진다
        again = state.note_boot(version="1.0.1", folder=self.folder)
        self.assertEqual((again.action, again.attempts_before), ("recovery_offered", 2))
        self.assertEqual((self.folder / "state.json").read_bytes(), before, "복구 안내는 아무것도 바꾸지 않는다 — 표식과 '띄웠다' 기록이 그대로 남는다")
        kept = self.state()
        self.assertEqual((kept.pending, kept.notice, kept.last_good), (pending, "rollback_launched", ""), "'되돌렸다' 고 적히지 않았고 정상 판 기록도 없다")
        second = self.session(current_version="1.0.1")
        self.assertEqual(second.on_boot(again), "RECOVERY_OFFERED")
        _outcome, restores_again = self.press_recover(second, popen)                       # 사용자가 다시 누르면 같은 복구가 다시 돈다(복원 직전 안전 사본 규칙 그대로)
        self.assertEqual((second.state, len(popen.calls), restores_again), ("ROLLED_BACK", 3, [(pending.backup_name, True)]))
        note = state.note_boot(version="1.0.0", folder=self.folder)                      # 이번에는 이전 판이 실제로 켜졌다
        self.assertEqual(note.action, "rolled_back")
        done = self.state()
        self.assertEqual((done.pending, done.notice, done.last_good, done.last_seq), (None, "rolled_back", "1.0.0", self.release.dict["seq"]))

    def test_the_recovery_asks_for_the_adapter_of_the_kind_stored_in_the_marker_and_never_assumes_inno(self):
        """독립 검증 S I2(변이 S27) — 복구가 저장된 `pending.kind` 를 무시하고 늘 Inno 어댑터를 고르는 틀린 코드는 겉으로 같은 거절이 나서(저장된 종류가 `velopack` 이어도 어댑터가 거절한다)
        결과만으로는 안 보인다 — 그래서 어떤 종류로 어댑터를 불렀는지를 본다: 표식에 적힌 종류 그대로여야 하고, `velopack`(읽기만 하는 종류)이면 아무것도 띄우지 않는다.
        데이터 복원은 설치 도구 단계보다 앞서 이미 끝나 있다(복원 직전 안전 사본 규칙) — 그래서 거절돼도 표식이 남고 '복구 실패' 안내가 적힌다."""
        self.keep_older_setup(kind="velopack")
        popen = FakePopen()
        _fresh, pending = self.offered_recovery(popen)
        stored = self.state()
        state.write_state(self.folder, dataclasses.replace(stored, pending=dataclasses.replace(stored.pending, kind="velopack")))
        launched = len(popen.calls)
        restores = []
        asked = []
        original = apply.adapter_for

        def spy(kind):
            asked.append(kind)
            return original(kind)
        with mock.patch.object(subprocess, "Popen", popen), mock.patch.object(backup_flow, "restore_full_backup", lambda ctx, name, *, confirmed, step=None: restores.append((name, confirmed))),                 mock.patch.object(update_flow.apply_module, "adapter_for", spy):
            with self.assertRaises(recovery.RollbackFailure) as caught:
                update_flow.recover_update(self.ctx, confirmed=True, keyring=fs.RING)
        self.assertEqual(asked, ["velopack"], "표식에 적힌 종류 그대로 어댑터를 불렀다")
        self.assertEqual((caught.exception.step, caught.exception.cause_code), ("apply", "UPDATE_APPLY_FAILED"))
        self.assertEqual(len(popen.calls), launched, "어댑터가 없는 종류라 아무것도 띄우지 않았다")
        after = self.state()
        self.assertEqual((after.pending.kind, after.notice), ("velopack", "rollback_failed"))
        self.assertEqual(restores, [(pending.backup_name, True)])

    def test_a_setup_that_cannot_even_be_started_is_the_apply_failure_and_leaves_the_old_version_untouched(self):
        popen = FakePopen(error=OSError(193, "CANARY_" + "NOT_A_PROGRAM"))
        with mock.patch.object(subprocess, "Popen", popen):
            session = self.session()
            session.check()
            session.download()
            with self.assertRaises(AppError) as caught:
                session.apply(confirmed=True)
        self.assertEqual((caught.exception.code, caught.exception.detail, session.state), ("UPDATE_APPLY_FAILED", "launch_failed", "IDLE"))
        after = self.state()
        self.assertEqual((after.pending, after.last_seq), (None, 0), "표식을 지웠고 시퀀스는 그대로 — 지금 판 그대로")
        self.assertNotIn("CANARY_", str(caught.exception.log_line()))

    def test_a_tampered_download_is_refused_by_the_flow_before_the_adapter_and_never_launches(self):
        popen = FakePopen()
        with mock.patch.object(subprocess, "Popen", popen):
            session = self.session()
            session.check()
            staged = session.download()
            path = staged.files["setup"]
            path.write_bytes(path.read_bytes()[:-1] + b"X")
            with self.assertRaises(AppError) as caught:
                session.apply(confirmed=True)
        self.assertEqual(caught.exception.code, "UPDATE_SIGNATURE_INVALID")
        self.assertEqual(popen.calls, [])


class NoExitCodeTest(unittest.TestCase):
    NAMES = {"wait", "poll", "communicate", "returncode", "check_returncode", "pid", "kill", "terminate", "send_signal", "stdout", "stderr", "stdin"}

    def test_the_adapter_and_the_flow_never_ask_a_process_for_its_exit_code_output_or_end(self):
        for path in (SRC / "update" / "apply.py", SRC / "service" / "update_flow.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            found = sorted({node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute) and node.attr in self.NAMES})
            self.assertEqual(found, [], f"{path.name}: 프로세스 개체의 {found} 를 부른다 — 앱은 Setup 을 기다리지 않는다(앱이 먼저 끝난다)")

    def test_the_launcher_does_not_even_keep_the_process_object(self):
        tree = ast.parse((SRC / "update" / "apply.py").read_text(encoding="utf-8"))
        launcher = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "launch_setup")
        calls = [node for node in ast.walk(launcher) if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call) and ast.unparse(node.value.func) == "subprocess.Popen"]
        self.assertEqual(len(calls), 1, "Popen 호출의 결과를 받아 두지 않는다(식 문장)")


def silent_args_problem(update_args, namespace):
    """앱의 무음 인자(`update_args`)와 설치 구현 갈래의 단일 출처(`namespace` — `packaging/pkgcommon.py` 모양)가 같은가 → 다른 점을 적은 글(같으면 빈 글).
    설치 쪽 상수 `INNO_SILENT_INSTALL_ARGS` 에 '업데이트용 추가 인자'(이름에 `INNO_`·`UPDATE`·`ARGS` 가 든 상수)를 더한 집합이 앱의 고정 인자와 같아야 한다."""
    base = tuple(getattr(namespace, "INNO_SILENT_INSTALL_ARGS"))
    extra = ()
    for name in sorted(vars(namespace)):
        value = vars(namespace)[name]
        if name.startswith("INNO_") and "UPDATE" in name and name.endswith("ARGS") and isinstance(value, (tuple, list)):
            extra += tuple(value)
    wanted, got = set(base) | set(extra), set(update_args)
    if wanted != got:
        return f"앱에만 있는 인자 {sorted(got - wanted)} · 설치 쪽에만 있는 인자 {sorted(wanted - got)}"
    if "/CLOSEAPPLICATIONS" not in got or any(arg.startswith("/LOG") for arg in got | wanted):
        return "닫기 인자가 없거나 로그 인자가 고정 목록에 섞였다"
    return ""


class SharedSilentArgumentsTest(unittest.TestCase):
    """무음 인자의 단일 출처 짝 시험 — 설치 구현 갈래(V1INSTALL)가 `packaging/pkgcommon.py` 에 `INNO_SILENT_INSTALL_ARGS` 를 두면 저절로 켜진다(`VERSION_PATTERN`·`ui/core/version.py` 같음 지키기와 같은 모양).
    그 전에는 건너뛴다 — 건너뜀 이유는 이 시험의 이름과 설명에 있다. 비교 논리 자체는 아래 합성 시험이 늘 돌려 본다(건너뛰어도 비교가 헛돌지 않는다)."""
    HAVE = hasattr(pkgcommon, "INNO_SILENT_INSTALL_ARGS")

    def test_the_comparison_itself_sees_a_difference_in_synthetic_namespaces(self):
        """설치 쪽 값이 `/SP-` 를 포함하는 다섯 인자가 된 뒤(독립 검증 S R1 — 앱 쪽에 `/SP-` 를 더해 같게 했다)의 합성 값: 같은 값은 통과하고, 한 인자라도 어긋나면(앱이 `/SP-` 를 빼도) 걸린다."""
        same = SimpleNamespace(INNO_SILENT_INSTALL_ARGS=("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-"), INNO_UPDATE_EXTRA_ARGS=("/CLOSEAPPLICATIONS",), INNO_SILENT_UNINSTALL_ARGS=("/VERYSILENT",))
        self.assertEqual(silent_args_problem(apply.INNO_SILENT_ARGS, same), "")
        wide = SimpleNamespace(INNO_SILENT_INSTALL_ARGS=("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-", "/CLOSEAPPLICATIONS"))
        self.assertEqual(silent_args_problem(apply.INNO_SILENT_ARGS, wide), "")
        for label, namespace in (("인자 하나 빠짐", SimpleNamespace(INNO_SILENT_INSTALL_ARGS=("/VERYSILENT", "/NORESTART", "/SP-"), INNO_UPDATE_EXTRA_ARGS=("/CLOSEAPPLICATIONS",))),
                                 ("설치 쪽에만 있는 인자", SimpleNamespace(INNO_SILENT_INSTALL_ARGS=("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-", "/FORCECLOSEAPPLICATIONS"), INNO_UPDATE_EXTRA_ARGS=("/CLOSEAPPLICATIONS",))),
                                 ("닫기 인자 없음", SimpleNamespace(INNO_SILENT_INSTALL_ARGS=("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-"))),
                                 ("시작 확인창 인자가 설치 쪽에 없다", SimpleNamespace(INNO_SILENT_INSTALL_ARGS=("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"), INNO_UPDATE_EXTRA_ARGS=("/CLOSEAPPLICATIONS",)))):
            with self.subTest(label=label):
                self.assertNotEqual(silent_args_problem(apply.INNO_SILENT_ARGS, namespace), "")
        self.assertNotEqual(silent_args_problem(("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"), same), "", "앱 쪽에서 닫기 인자를 빼도 걸린다")
        self.assertNotEqual(silent_args_problem(("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS"), same), "", "앱 쪽에서 `/SP-` 를 빼도 걸린다(예전 넷 목록 — 독립 검증 S R1 이 이 불일치를 찾았다)")
        self.assertNotEqual(silent_args_problem(("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-"), same), "", "앱 쪽에서 닫기 인자만 빼도 걸린다")

    @unittest.skipUnless(HAVE, "건너뜀(V1INSTALL 병합 전) — packaging/pkgcommon.py 에 INNO_SILENT_INSTALL_ARGS 가 아직 없다. 병합되면 이 시험이 저절로 켜진다(총괄이 합칠 때 활성 여부를 확인한다)")
    def test_the_silent_arguments_equal_the_packaging_single_source_only_active_after_v1install_merges(self):
        self.assertEqual(silent_args_problem(apply.INNO_SILENT_ARGS, pkgcommon), "")

    @unittest.skipUnless(hasattr(pkgcommon, "INNO_SILENT_UPDATE_ARGS"), "건너뜀(V1INSTALL 병합 전) — packaging/pkgcommon.py 에 INNO_SILENT_UPDATE_ARGS 가 아직 없다. 병합되면 이 시험이 저절로 켜진다(총괄이 합칠 때 활성 여부를 확인한다)")
    def test_the_silent_arguments_equal_the_packaging_update_tuple_exactly_in_order_only_active_after_v1install_merges(self):
        """독립 검증 S R1 의 권고 — 위 짝 시험은 '이름에 UPDATE 가 든 상수들의 합집합' 이라 순서·중복을 못 본다. 설치 쪽이 업데이트용으로 이미 합쳐 둔 값(`INNO_SILENT_UPDATE_ARGS`)이 있으면 튜플 그대로(순서·중복까지) 견준다."""
        self.assertEqual(tuple(apply.INNO_SILENT_ARGS), tuple(pkgcommon.INNO_SILENT_UPDATE_ARGS))


@unittest.skipUnless(os.name == "nt", "윈도에서만 돈다 — 임시 폴더의 .cmd 가짜 Setup 을 진짜 launch_setup 으로 띄워 인자 목록·분리된 프로세스·부모가 끝난 뒤의 이어짐을 본다(다른 운영체제는 건너뜀)")
class DetachedLaunchIntegrationTest(unittest.TestCase):
    HELPER = '''import json, os, sys, time
folder = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(folder, "args.tmp"), "w", encoding="utf-8") as handle:
    json.dump({"argv": sys.argv[1:], "pid": os.getpid()}, handle)
os.replace(os.path.join(folder, "args.tmp"), os.path.join(folder, "args.json"))
end = time.monotonic() + 150
while time.monotonic() < end and not os.path.exists(os.path.join(folder, "go.txt")):
    time.sleep(0.2)
with open(os.path.join(folder, "done.txt"), "w", encoding="utf-8") as handle:
    handle.write("finished")
'''
    PARENT = '''import re, sys
sys.path.insert(0, sys.argv[1])
from chanceblog_desktop import capabilities
from chanceblog_desktop.update import apply
capabilities.UPDATE_APPLY = True
apply.SETUP_NAME = re.compile(sys.argv[4])
apply.launch_setup(sys.argv[2], sys.argv[3])
'''

    @staticmethod
    def wait_for(path, seconds=120):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if path.exists():
                return True
            time.sleep(0.25)
        return False

    def test_a_fake_setup_gets_the_fixed_arguments_and_keeps_running_after_the_app_process_has_ended(self):
        holder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(holder.cleanup)
        folder = Path(holder.name) / "Update Folder with spaces"
        folder.mkdir()
        (folder / "fake_setup_helper.py").write_text(self.HELPER, encoding="utf-8")
        pythonw = Path(sys.executable).with_name("pythonw.exe")
        runner = pythonw if pythonw.is_file() else Path(sys.executable)
        fake = folder / "fake-setup.cmd"
        fake.write_bytes(f'@"{runner}" "{folder / "fake_setup_helper.py"}" %*\r\n'.encode("utf-8"))
        log = folder / apply.UPDATE_LOG_NAME
        self.addCleanup(lambda: (folder / "go.txt").write_text("go", encoding="utf-8") if folder.exists() and not (folder / "done.txt").exists() else None)
        started = time.monotonic()
        done = subprocess.run([sys.executable, "-X", "utf8", "-c", self.PARENT, str(ROOT / "src"), str(fake), str(log), re.escape(fake.name)], capture_output=True, timeout=90)       # 가짜 Setup 이 .cmd 라 이름 규칙(독립 검증 S R6)을 이 자식 프로세스 안에서만 가짜 이름으로 바꾼다 — 소스에는 설치 도구 이름을 새로 두지 않는다
        self.assertEqual(done.returncode, 0, (done.stdout + done.stderr)[-400:])
        self.assertLess(time.monotonic() - started, 85, "앱 역할의 프로세스는 Setup 을 기다리지 않고 곧 끝났다(표준 입출력을 물려받았다면 여기서 막혔을 것이다)")
        self.assertTrue(self.wait_for(folder / "args.json"), "가짜 Setup 이 시작되지 않았다")
        received = json.loads((folder / "args.json").read_text(encoding="utf-8"))
        self.assertEqual(received["argv"], [*FIXED_ARGS, "/LOG=" + str(log)], "공백이 든 폴더에서도 인자 목록이 그대로 도착한다")
        self.assertFalse((folder / "done.txt").exists(), "앱 역할의 프로세스가 끝난 지금도 가짜 Setup 은 아직 일하는 중이다")
        (folder / "go.txt").write_text("go", encoding="utf-8")
        self.assertTrue(self.wait_for(folder / "done.txt"), "부모가 끝난 뒤에도 가짜 Setup 이 끝까지 이어졌다")


if __name__ == "__main__":
    unittest.main()
