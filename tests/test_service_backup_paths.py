"""조작한 백업의 설정(`settings.json`)이 '연결한 폴더' 자리에 남의 서버를 가리키는 경로를 몰래 넣지 못하게 하는 시험 — 전체 백업 복원(`service/backup_flow.py`)의 `_repo_path_problem`과 JSON·설정의 크기 상한 (L8, 결정 D-554).

위협: 설정의 `repo_path` 는 어떤 글이든 받았다. 복원이 끝나면 앱은 그 경로가 폴더인지 알아보려고 열어 본다(복원 직후의 안내·이후의 점검). 조작한 백업이 네트워크 경로(UNC)를 넣으면 이 PC 가 그 서버에 접속하며 윈도 로그인 정보를 보낼 수 있다.
지키는 것:
  1) 보통 폴더 경로 모양(빈 글·드라이브 경로·상대 경로·홈 폴더 약식 경로·한글 이름·공백)은 그대로 받고, 네트워크 경로(역슬래시·슬래시 둘로 시작하는 서버 경로·확장·장치 경로)·주소(`://`)·제어 문자(보이지 않는 글자 포함)·1024자를 넘는 글은 거절한다 — 경계(1024자)가 정확하다.
  2) 조작한 설정이 든 백업은 **바꾸기 전에** 거절한다(`FULL_BACKUP_INVALID` 이유 `content` — 지금 데이터·안전 사본 폴더·표지·잠금이 그대로) 이 PC 는 그 경로를 열어 보지도 않는다(경로 확인 호출을 감시한다). 문구·오류 세부에 경로 글이 없다.
  3) 정상 백업(연결한 폴더가 이 PC 의 폴더)은 그대로 되돌려지고 백업을 만드는 쪽은 바뀌지 않았다(UNC 경로가 든 설정도 백업은 만들어지고 복원만 거절한다 — 문서의 한계).
  4) 설정 파일에 넣을 수 있는 이상한 글(깊이 겹친 JSON·NaN·무한대·문자 아닌 경로·덜 짝맞춘 서로게이트·NUL·BOM·UTF-8 아닌 바이트·빈 파일·모르는 칸)은 모두 쉬운 거절이다 — 예전에는 깊이 겹친 JSON 에서 `RecursionError` 가 그대로 새어 나갔다.
  5) JSON·설정 파일은 앱이 백업을 만들 때 쓰는 상한(8MB)을 넘으면 읽기 전에 거절한다(정확히 8MB 는 받는다). 보관함 파일에는 이 묶음이 상한을 정하지 않았다.
네트워크·실제 시계·실제 자격 증명 관리자 없이 돈다. 가짜 서버 이름에는 `CANARY` 글자를 넣는다.
"""
import hashlib
import json
import os
import random
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import backup_support as bs  # noqa: E402
import test_service_backup_restore as tr  # noqa: E402

from chanceblog_desktop.service import backup_flow as bf  # noqa: E402
from chanceblog_desktop.topics import layout  # noqa: E402

BS = chr(92)                                                                         # 역슬래시 — 소스에 이스케이프를 쓰지 않는다
HOST = "CANARY_host.example"
GOOD = ("", "chanceblog", "C:" + BS + "Users" + BS + "me" + BS + "chanceblog", "D:/repos/chanceblog", chr(126) + "/chanceblog", "../chanceblog", "/home/me/chanceblog", "한글 폴더/블로그",
        "C:" + BS + "a b" + BS + "c", "relative" + BS + "path", "C:/x", "a" * bf.MAX_REPO_PATH, "C:" + BS + "x:y", "x:" + BS + "y",
        # AS-S1 필수-3(D-605) — 허용 목록이 계속 받아야 하는 보통 경로들: 드라이브 글자(소문자·슬래시 섞임)·홈 약식·상대 경로·드라이브 상대·구분자 하나로 시작하는 경로·NT 접두와 닮았지만 아닌 이름
        "c:" + BS + "x", "C:/x" + BS + "y/z", chr(126), chr(126) + "other/x", "..", ".", "C:x", "C:", BS + "Users" + BS + "me", "/dosdevicesx/y", "/global/x", "/devices/x", "/??x/y", "GLOBALROOT/Device/x", "a/??/b",
        "한글" + BS + "경로" + BS + "x", "D:" + BS + "블로그 저장소", "%USERPROFILE%" + BS + "x", "C:" + BS + "x::$DATA")
BAD = {
    "network": (BS * 2 + HOST + BS + "share" + BS + "repo", "//" + HOST + "/share/repo", BS * 2 + "?" + BS + "C:" + BS + "x", BS * 2 + "." + BS + "pipe" + BS + "x", "/" + BS + HOST + BS + "x",
                BS + "/" + HOST + "/x", BS * 3 + HOST,
                # AS-S1 필수-3(D-605) — NT 이름공간 표기(윈도 파일 호출이 네트워크 공급자로 보낸다)·대소문자·슬래시·앞 공백 변형. 뒤의 둘은 로컬 폴더를 가리키는 NT 표기라도 보통 경로가 아니므로 받지 않는다.
                BS + "??" + BS + "UNC" + BS + HOST + BS + "share" + BS + "x", "/??/UNC/" + HOST + "/share/x", BS + "??" + BS + "GLOBALROOT" + BS + "Device" + BS + "Mup" + BS + HOST + BS + "share",
                BS + "??" + BS + "unc" + BS + HOST, BS + "??" + BS + "Unc" + "/" + HOST, "/??" + BS + "UNC/" + HOST, "/??/GLOBALROOT/Device/Mup/" + HOST + "/share",
                BS + "DosDevices" + BS + "UNC" + BS + HOST + BS + "x", BS + "dosdevices" + BS + "unc" + BS + HOST, "/DOSDEVICES/UNC/" + HOST + "/x", BS + "GLOBAL??" + BS + "UNC" + BS + HOST, "/global??/UNC/" + HOST,
                BS + "Global??" + BS + "GLOBALROOT" + BS + "Device" + BS + "Mup" + BS + HOST, " " + BS * 2 + HOST + BS + "share", chr(0xA0) + BS * 2 + HOST + BS + "x", " /??/UNC/" + HOST, "  " + BS + "??" + BS + "UNC" + BS + HOST,
                BS + "??", "/??", BS + "??" + BS + "C:" + BS + "Windows", BS + "??" + BS + "c:", "/dosdevices", BS + "GLOBAL??"),
    "url": ("https://" + HOST + "/x", "file:///C:/x", "ftp://" + HOST + "/y", "C:/x://y", "smb://" + HOST + "/s"),
    "control": ("C:" + BS + "x" + chr(10) + "y", "C:/x" + chr(0) + "y", "C:/x" + chr(0x202E) + "y", "C:/x" + chr(0x200B), "C:/x" + chr(0x2028), chr(7) + "C:/x", "C:/x" + chr(0x7F), "C:/x" + chr(0xE000), "C:/x" + chr(0x2029), "C:/x" + chr(0x0378)),
    "length": ("C:/" + "a" * 1100, "a" * (bf.MAX_REPO_PATH + 1)),
}
# AS-S1 2차(안전 검증 S) 필수-1(D-616) — 점 마디·겹친 구분자 접두 뒤에 NT 이름이 오는 글(검증자 탐침 `probe_path_guard_normalize` 의 구조). 앱은 `Path(os.path.expanduser(글))` 로 정리한 글을 여는데 pathlib 은 겹친 구분자와 `.` 마디를
# 지우고 다시 만들어서 이 글들은 열 때 NT 이름공간 표기가 된다.
DOT_LEADS = ("/./", BS + "." + BS, "/.//", BS + "." + BS + "." + BS, "/././", "/." + BS + BS, BS + "." + BS + "/", "/.//./")
DOTDOT_LEADS = ("/..//..", BS + ".." + BS + ".." + BS)                                   # `..` 마디는 pathlib 이 지우지 않는다 — 정리한 글에도 남아 NT 접두가 되지 않는다(아래 시험 설명)
NT_FORMS = ("??" + BS + "UNC" + BS + HOST + BS + "share", "??/UNC/" + HOST + "/share", "??" + BS + "GLOBALROOT" + BS + "Device" + BS + "Mup" + BS + HOST + BS + "share", "??" + BS + "unc" + BS + HOST,
            "??" + BS + "C:" + BS + "x")
BAD["network"] += (DOT_LEADS[0] + NT_FORMS[1], DOT_LEADS[1] + NT_FORMS[0], DOT_LEADS[2] + NT_FORMS[2], DOT_LEADS[7] + NT_FORMS[3])    # 끝에서 끝까지 시험(조작한 백업·복원 직후 열기)이 이 넷을 함께 돈다


class RuleTest(unittest.TestCase):
    def test_ordinary_folder_paths_are_accepted_exactly_up_to_the_limit(self):
        for text in GOOD:
            with self.subTest(text=text[:30]):
                self.assertEqual(bf._repo_path_problem(text), "")
        self.assertEqual(bf.MAX_REPO_PATH, 1024)
        self.assertEqual(bf._repo_path_problem("a" * 1024), "")
        self.assertEqual(bf._repo_path_problem("a" * 1025), "length")

    def test_every_dangerous_shape_is_named_by_its_fixed_word(self):
        for word, texts in BAD.items():
            for text in texts:
                with self.subTest(word=word, text=text[:30]):
                    self.assertEqual(bf._repo_path_problem(text), word)

    def test_the_first_matching_rule_names_the_problem_and_the_word_never_repeats_the_text(self):
        self.assertEqual(bf._repo_path_problem(BS * 2 + HOST + "a" * 2000), "length", "길이가 먼저")
        self.assertEqual(bf._repo_path_problem(BS * 2 + HOST + chr(10)), "control", "제어 문자가 네트워크보다 먼저")
        self.assertEqual(bf._repo_path_problem(BS * 2 + HOST + "://x"), "network", "네트워크가 주소보다 먼저")
        for word in ("length", "control", "network", "url"):
            self.assertNotIn(HOST, word)


class ForgedBackup(tr.Base):
    """백업을 하나 만들어 두고 그 폴더의 파일을 조작한 뒤 목록의 크기·해시를 다시 계산하는(조작한 사람이 하는 일) 틀."""

    def setUp(self):
        super().setUp()
        self.outcome = self.world.backup()
        self.folder = self.world.folder(self.outcome)
        tr.change_everything(self.world)
        self.before = tr.state_of(self.world)

    def forge_bytes(self, name, raw):
        (self.folder / name).write_bytes(raw)
        manifest = json.loads((self.folder / bf.MANIFEST_NAME).read_text(encoding="utf-8"))
        manifest["files"][name].update(size=len(raw), sha256=hashlib.sha256(raw).hexdigest())
        bs.write_manifest(self.folder, manifest)

    def forge_settings(self, repo_path):
        data = json.loads((self.folder / "settings.json").read_text(encoding="utf-8"))
        data["repo_path"] = repo_path
        self.forge_bytes("settings.json", (json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + chr(10)).encode("utf-8"))

    def assert_refused_before_anything_changed(self, reason="content"):
        error = bs.code_of(bf.restore_full_backup, self.ctx, self.outcome.row.name, confirmed=True)
        self.assertIsNotNone(error, "거절돼야 한다")
        self.assertEqual((error.code, error.reason), ("FULL_BACKUP_INVALID", reason), error.detail)
        self.assert_untouched(self.before)
        return error


class RestoreTest(ForgedBackup):
    def test_a_backup_whose_settings_point_at_a_foreign_path_is_refused_before_anything_changes_and_the_path_is_never_opened(self):
        for word, texts in BAD.items():
            for text in texts:
                with self.subTest(word=word, text=text[:30]):
                    original = (self.folder / "settings.json").read_bytes(), (self.folder / bf.MANIFEST_NAME).read_bytes()
                    opened = []
                    real = Path.is_dir

                    def spy(self_path):
                        opened.append(str(self_path))
                        return real(self_path)

                    try:
                        self.forge_settings(text)
                        with mock.patch.object(Path, "is_dir", spy):
                            error = self.assert_refused_before_anything_changed()
                        self.assertIn("settings.json", error.detail)
                        self.assertIn(f"({word})", error.detail, "이유의 고정 낱말")
                        self.assertNotIn(HOST, str(error) + error.log_line() + error.detail, "경로 글을 되풀이하지 않는다")
                        self.assertFalse([item for item in opened if HOST in item], "그 경로는 열어 보지도 않는다")
                    finally:
                        (self.folder / "settings.json").write_bytes(original[0])
                        (self.folder / bf.MANIFEST_NAME).write_bytes(original[1])

    def test_a_backup_with_an_ordinary_connected_folder_restores_and_says_when_that_folder_is_missing(self):
        self.forge_settings("C:" + BS + "no" + BS + "such" + BS + "chanceblog-folder")
        result = self.restore(self.outcome.row.name)
        self.assertEqual(result.status, bf.STATUS_COMPLETE)
        self.assertTrue(any("연결해 둔 chanceblog 폴더를 이 PC 에서 찾지 못했어요" in note for note in result.notes))

    def test_the_backup_side_is_unchanged_a_foreign_path_in_live_settings_is_still_backed_up(self):
        """백업을 만드는 쪽은 지금 파일을 그대로 담는다 — 사용자가 직접 정한 값이면 백업은 만들어지고, 복원만 거절된다(문서의 한계)."""
        self.ctx.settings.save_repo_path(BS * 2 + HOST + BS + "share")
        made = self.world.backup()
        self.assertEqual(made.row.status, bf.STATUS_COMPLETE)
        error = bs.code_of(bf.restore_full_backup, self.ctx, made.row.name, confirmed=True)
        self.assertEqual((error.code, error.reason), ("FULL_BACKUP_INVALID", "content"))

    def test_the_check_runs_in_the_first_verification_before_the_lock_and_the_safety_copy(self):
        self.forge_settings("//" + HOST + "/x")
        with mock.patch.object(bf, "_flow_lock", side_effect=AssertionError("잠금을 잡기 전에 거절해야 한다")):
            error = bs.code_of(bf.restore_full_backup, self.ctx, self.outcome.row.name, confirmed=True)
        self.assertEqual(error.code, "FULL_BACKUP_INVALID")


class AllowListTest(unittest.TestCase):
    """AS-S1 필수-3(D-605) — '연결한 폴더' 글의 네트워크 경로 가드가 거절 목록(역슬래시 둘로 시작할 때만 network)에서 **허용 목록**으로 바뀌었다. 윈도 파일 호출은 NT 이름공간 접두 `\\??\\` 를
    그대로 받아 `\\??\\UNC\\서버\\공유` 를 네트워크 공급자로 보내는데 옛 가드는 그 글을 빈 글(받음)로 판정했다. 이 시험은 순수 글자 판정이라 모든 운영체제에서 돌고 네트워크·UNC 를 부르지 않는다."""

    NT_NAMES = ("??", "DosDevices", "GLOBAL??")

    def test_the_allow_list_accepts_exactly_the_four_plain_shapes(self):
        """① 빈 글 ② 드라이브 글자 절대경로 ③ 맨 앞이 구분자가 아닌 글(상대·홈 약식) ④ 구분자 하나로 시작하는 경로(NT 접두 제외)."""
        for text in ("", "C:" + BS + "x", "z:/y", "relative/x", chr(126) + "/x", "../x", BS + "Users" + BS + "me", "/home/me/x", "/devices/x"):
            with self.subTest(text=text):
                self.assertTrue(bf._plain_local_shape(text))
        for text in (BS * 2 + HOST, "//" + HOST, BS + "??" + BS + "UNC" + BS + HOST, "/??/UNC/" + HOST, BS + "DosDevices" + BS + "x", BS + "GLOBAL??" + BS + "x", " " + BS * 2 + HOST):
            with self.subTest(text=text):
                self.assertFalse(bf._plain_local_shape(text))

    def test_every_nt_namespace_spelling_is_network_in_any_case_with_either_separator_and_leading_spaces(self):
        tails = ("", "{s}UNC{s}" + HOST + "{s}share", "{s}GLOBALROOT{s}Device{s}Mup{s}" + HOST, "{s}C:{s}Windows")
        count = 0
        for name in self.NT_NAMES:
            for spelling in (name, name.lower(), name.upper(), name.title()):
                for lead in ("", " ", "  ", chr(0xA0), chr(0x3000)):
                    for first in (BS, "/"):
                        for sep in (BS, "/"):
                            for tail in tails:
                                text = lead + first + spelling + tail.format(s=sep)
                                with self.subTest(text=text):
                                    self.assertEqual(bf._repo_path_problem(text), "network")
                                count += 1
        self.assertEqual(count, 960, "세 이름 × 네 철자 × 앞 공백 다섯 × 첫 구분자 둘 × 나머지 구분자 둘 × 꼬리 넷")

    def test_two_or_more_leading_separators_in_any_mix_are_network_and_a_single_one_is_not(self):
        for first in (BS, "/"):
            for second in (BS, "/"):
                for more in ("", BS, "/"):
                    text = first + second + more + HOST + "/share"
                    with self.subTest(text=text):
                        self.assertEqual(bf._repo_path_problem(text), "network")
        for text in (BS + HOST, "/" + HOST, "/" + HOST + "/share", BS + HOST + BS + "share"):
            with self.subTest(text=text):
                self.assertEqual(bf._repo_path_problem(text), "", "구분자 하나로 시작하는 경로는 이 PC 의 드라이브 뿌리 경로다")

    def test_drive_paths_and_relative_paths_are_accepted_whatever_the_letter_or_separator(self):
        letters = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
        for letter in letters:
            for sep in (BS, "/"):
                with self.subTest(letter=letter, sep=sep):
                    self.assertEqual(bf._repo_path_problem(letter + ":" + sep + "blog" + sep + "chanceblog"), "")
        for text in ("blog" + BS + "chanceblog", "../x", chr(126) + BS + "x", "x" * 100, "한글 폴더/블로그", "C:relative", "NUL", "GLOBALROOT" + BS + "Device" + BS + "x"):
            with self.subTest(text=text):
                self.assertEqual(bf._repo_path_problem(text), "")

    def test_the_audit_probe_table_gets_the_same_answers_as_before_except_the_nt_forms_which_are_now_refused(self):
        """감사 탐침 p6 의 스물 몇 가지 — 옛 가드가 이미 잘 막던 모양은 **같은 낱말**로 막히고, 새로 막히는 것은 NT 표기(와 앞 공백·NBSP 를 붙인 UNC)뿐이다. 환경 변수 꼴·사용자 이름이 붙은 홈 약식·대체 데이터 흐름·매핑된 드라이브 글자는 글자만으로는 알 수 없어 받는다(알려진 한계)."""
        table = {
            "unc backslash": (BS * 2 + "srv" + BS + "share" + BS + "x", "network"), "unc slash": ("//srv/share/x", "network"), "extended unc": (BS * 2 + "?" + BS + "UNC" + BS + "srv" + BS + "share" + BS + "x", "network"),
            "device path": (BS * 2 + "." + BS + "pipe" + BS + "x", "network"), "webdav ssl": (BS * 2 + "srv@SSL" + BS + "DavWWWRoot" + BS + "x", "network"), "triple slash": ("///srv/share", "network"),
            "bidi override unc": (chr(0x202A) + BS * 2 + "srv" + BS + "share", "control"), "file url": ("file" + ":///c:/x", "url"), "http url": ("http" + ":" + "//evil.invalid/x", "url"), "http with backslashes": ("http:" + BS * 2 + "evil" + BS + "x", ""),
            "mapped drive letter": ("Z:" + BS + "mapped" + BS + "x", ""), "relative traversal": (".." + BS + ".." + BS + "x", ""), "env var": ("%USERPROFILE%" + BS + "x", ""), "tilde user": (chr(126) + "someone" + BS + "x", ""),
            "ads": ("C:" + BS + "x::$DATA", ""), "plain": ("C:" + BS + "work" + BS + "blog", ""), "empty": ("", ""),
            # 옛 가드가 받던(=뚫리던) 모양 — 이제 network
            "nt namespace single backslash": (BS + "??" + BS + "UNC" + BS + "srv" + BS + "share" + BS + "x", "network"), "nt namespace slash": ("/??/UNC/srv/share/x", "network"),
            "nt globalroot mup": (BS + "??" + BS + "GLOBALROOT" + BS + "Device" + BS + "Mup" + BS + "srv" + BS + "share", "network"), "leading space unc": (" " + BS * 2 + "srv" + BS + "share" + BS + "x", "network"),
            "nbsp unc": (chr(0xA0) + BS * 2 + "srv" + BS + "share" + BS + "x", "network"),
        }
        for label, (text, expected) in table.items():
            with self.subTest(label=label):
                self.assertEqual(bf._repo_path_problem(text), expected)

    def test_the_decision_is_pure_text_it_asks_neither_the_file_system_nor_the_network(self):
        boom = AssertionError("글자 판정이 파일 시스템·네트워크를 불렀다")
        import os
        import socket
        with mock.patch.object(Path, "is_dir", side_effect=boom), mock.patch.object(Path, "exists", side_effect=boom), mock.patch.object(Path, "resolve", side_effect=boom), \
                mock.patch.object(os, "stat", side_effect=boom), mock.patch.object(os, "lstat", side_effect=boom), mock.patch.object(os.path, "exists", side_effect=boom), \
                mock.patch.object(os.path, "isdir", side_effect=boom), mock.patch.object(socket, "socket", side_effect=boom), mock.patch.object(socket, "getaddrinfo", side_effect=boom):
            for text in [*GOOD, *(item for texts in BAD.values() for item in texts)]:
                bf._repo_path_problem(text)

    def test_the_old_reject_list_shape_is_gone_the_function_is_the_allow_list(self):
        import inspect
        source = inspect.getsource(bf._repo_path_problem) + inspect.getsource(bf._plain_local_shape)
        self.assertNotIn('startswith("\\\\\\\\")', source.replace(" ", ""), "옛 거절 목록(역슬래시 둘로 시작할 때만)이 남아 있다")
        self.assertIn("_NT_NAMESPACE", source)
        self.assertEqual(bf._DRIVE_ABSOLUTE.pattern, "[A-Za-z]:" + BS * 2)


class DotSegmentTest(unittest.TestCase):
    """AS-S1 2차(안전 검증 S) 필수-1(D-616) — 가드가 글자 **그대로**만 보던 틈. '슬래시 점 슬래시 물음표 물음표 슬래시 UNC 슬래시 서버 슬래시 공유' 꼴의 글은 맨 앞 구분자 바로 뒤가 `.` 이라 보통 경로로 판정됐는데,
    앱이 여는 글(`Path(os.path.expanduser(글))` — pathlib 이 겹친 구분자와 `.` 마디를 지우고 다시 만든다)은 NT 이름공간 표기의 UNC 경로였다 — 감사 필수-3 이 막으려던 바로 그 글이다. 이제 원문과 앱이 여는 글(`_opened_text` — 윈도 방식 정리)
    **둘 다** 보통 경로 모양일 때만 받는다. 순수 글자 판정이라 모든 운영체제에서 돌고 네트워크·UNC 를 부르지 않는다.

    `..` 마디가 앞에 오는 글은 일부러 받는다: pathlib 은 `..` 마디를 지우지 않아 정리한 글에도 `..` 가 남아 NT 접두가 되지 않고, 윈도는 `..` 를 현재 드라이브의 뿌리 안으로 풀어 이 PC 의 폴더가 된다(네트워크로 가지 않는다 — 윈도 자신의 글자 변환으로 확인했다)."""

    def test_dot_segment_and_doubled_separator_prefixes_before_an_nt_name_are_network_with_or_without_leading_spaces(self):
        count = 0
        for lead in DOT_LEADS:
            for form in NT_FORMS:
                for prefix in ("", " ", chr(0xA0)):
                    text = prefix + lead + form
                    with self.subTest(text=text):
                        self.assertEqual(bf._repo_path_problem(text), "network")
                    count += 1
        self.assertEqual(count, 8 * 5 * 3, "여덟 접두 × 다섯 NT 꼴 × 앞 공백 셋")

    def test_the_dot_dot_prefixes_stay_accepted_because_the_text_the_app_opens_has_no_nt_prefix(self):
        count = 0
        for lead in DOTDOT_LEADS:
            for form in NT_FORMS:
                text = lead + form
                with self.subTest(text=text):
                    self.assertEqual(bf._repo_path_problem(text), "", "`..` 마디는 정리 뒤에도 남아 NT 접두가 되지 않는다")
                    opened = bf._opened_text(text)
                    self.assertIsNone(bf._NT_NAMESPACE.match(opened.lstrip().replace("/", BS)), "정리한 글이 NT 접두로 시작하지 않는다")
                count += 1
        self.assertEqual(count, 2 * 5)

    def test_the_app_opens_the_normalised_text_and_the_guard_judges_both_the_text_and_that_normalised_text(self):
        text = "/./??/UNC/" + HOST + "/share"
        self.assertEqual(bf._opened_text(text), BS + "??" + BS + "UNC" + BS + HOST + BS + "share", "pathlib 이 점 마디를 지우면 NT 이름공간 표기가 된다")
        seen = []
        real = bf._plain_local_shape

        def spy(value):
            seen.append(value)
            return real(value)

        with mock.patch.object(bf, "_plain_local_shape", spy):
            bf._repo_path_problem(text)
        self.assertIn(text, seen)
        self.assertIn(bf._opened_text(text), seen)

    def test_an_accepted_text_stays_accepted_after_the_apps_own_normalisation(self):
        """속성 시험(시드 고정) — 앞 구분자·`.`·`..`·공백 조합 × NT 꼴을 구조 무작위로 만들어, 받은 글은 앱이 여는 글(정리한 글)도 같은 판정으로 받는지 본다. 거꾸로 말하면 '정리하면 NT 접두·UNC 가 되는 글' 은 원문이 어떻게 생겼든 거절된다."""
        rng = random.Random(2026)
        leads = (BS, "/", ".", "..", " ", BS * 2, "//", "." + BS, "./", chr(0xA0))
        bodies = (*NT_FORMS, "??", "DosDevices" + BS + "UNC" + BS + HOST, "GLOBAL??" + BS + "UNC" + BS + HOST, "x" + BS + "y", "C:" + BS + "x", "pipe" + BS + "x")
        accepted = refused = 0
        for _ in range(6000):
            text = "".join(rng.choice(leads) for _ in range(rng.randint(0, 6))) + rng.choice(bodies)
            if rng.random() < 0.3:
                text += rng.choice(("", BS, "/", ".", " "))
            opened = bf._opened_text(text)                               # 앱은 한 번만 정리한다 — 두 번 정리해도 같은지는 묻지 않는다(파이썬 3.10 의 `PureWindowsPath` 는 '두 구분자 + 점 + 물음표' 꼴에서 두 번째 정리가 달라진다)
            if bf._repo_path_problem(text) == "":
                accepted += 1
                self.assertTrue(bf._plain_local_shape(opened), f"받은 글을 정리하니 보통 경로 모양이 아니게 됐다: {text!r} -> {opened!r}")
                if bf._opened_text(opened) == opened:                    # 정리가 안정인 글(거의 전부)은 정리한 글을 처음부터 다시 판정해도 같은 판정이다
                    self.assertEqual(bf._repo_path_problem(opened), "", f"{text!r} -> {opened!r}")
            else:
                refused += 1
        self.assertGreater(accepted, 1000, "받는 글이 너무 적으면 속성 시험이 비어 초록이 된다")
        self.assertGreater(refused, 1000, "거절하는 글이 너무 적으면 속성 시험이 비어 초록이 된다")

    @unittest.skipUnless(os.name == "nt", "윈도의 `Path` 가 하는 정리를 `PureWindowsPath` 가 그대로 흉내 내는지는 윈도에서만 마주 볼 수 있다")
    def test_on_windows_the_opened_text_is_exactly_what_path_would_open(self):
        texts = [*GOOD, *(item for texts in BAD.values() for item in texts), *(lead + form for lead in DOT_LEADS + DOTDOT_LEADS for form in NT_FORMS)]
        for text in texts:
            if chr(0) in text:
                continue
            with self.subTest(text=text[:30]):
                self.assertEqual(bf._opened_text(text), str(Path(os.path.expanduser(text))))

    def test_ordinary_paths_are_still_accepted_after_the_second_judgement(self):
        for text in ("C:" + BS + "Users" + BS + "me" + BS + "blog", "blog", "relative" + BS + "dir", "../blog", "/home/me/blog", chr(126) + "/blog", "한글 폴더/블로그", "C:/x", ".", "a b" + BS + "c", "", "..", "./x", "C:x"):
            with self.subTest(text=text):
                self.assertEqual(bf._repo_path_problem(text), "")


class OutcomeGuardTest(ForgedBackup):
    """복원이 끝난 뒤 그 경로를 폴더인지 알아보는 곳(`_outcome`)도 같은 허용 목록을 한 번 더 거친다 — 보통 폴더 경로 모양이 아니면 열어 보지 않는다(D-605)."""

    def test_a_path_that_is_not_a_plain_folder_path_is_never_opened_after_a_restore(self):
        manifest = self.world.manifest(self.outcome)
        for text in (BS + "??" + BS + "UNC" + BS + HOST + BS + "share", "/??/UNC/" + HOST + "/share", BS * 2 + HOST + BS + "share", BS + "DosDevices" + BS + "UNC" + BS + HOST, " " + BS * 2 + HOST,
                     DOT_LEADS[0] + NT_FORMS[1], DOT_LEADS[3] + NT_FORMS[0]):
            with self.subTest(text=text):
                self.ctx.settings.save_repo_path(text)
                opened = []
                real = Path.is_dir

                def spy(self_path):
                    opened.append(str(self_path))
                    return real(self_path)

                with mock.patch.object(Path, "is_dir", spy):
                    result = bf._outcome(self.ctx, self.folder, manifest, [], {}, None)
                self.assertEqual([item for item in opened if HOST in item], [], "그 경로는 열어 보지도 않는다")
                self.assertTrue(any("보통 폴더 경로 모양이 아니라서 열어 보지 않았어요" in note for note in result.notes), result.notes)
                self.assertNotIn(HOST, " ".join(result.notes), "경로 글을 되풀이하지 않는다")

    def test_a_plain_missing_folder_still_gets_the_old_note_and_is_asked_about(self):
        manifest = self.world.manifest(self.outcome)
        missing = "C:" + BS + "no" + BS + "such" + BS + "folder-" + HOST
        self.ctx.settings.save_repo_path(missing)
        asked = []
        real = Path.is_dir

        def spy(self_path):
            asked.append(str(self_path))
            return real(self_path)

        with mock.patch.object(Path, "is_dir", spy):
            result = bf._outcome(self.ctx, self.folder, manifest, [], {}, None)
        self.assertTrue([item for item in asked if HOST in item], "보통 경로는 예전처럼 열어 본다")
        self.assertTrue(any("연결해 둔 chanceblog 폴더를 이 PC 에서 찾지 못했어요" in note for note in result.notes))
        self.assertFalse(any("열어 보지 않았어요" in note for note in result.notes))


class AdversarialTest(ForgedBackup):
    """설정 파일에 넣을 수 있는 이상한 글 — 모두 쉬운 거절이다(예외가 그대로 새지 않는다). 깊이 겹친 JSON 은 예전에 `RecursionError` 가 새어 나갔다."""

    def payloads(self):
        ok = '{"schema": 1, "repo_path": %s, "naver_profiles": {}}'
        return {
            "deep lists": b"[" * 100_000 + b"]" * 100_000,
            "deep dicts": b'{"a":' * 100_000 + b"1" + b"}" * 100_000,
            "NaN schema": b'{"schema": NaN, "repo_path": "", "naver_profiles": {}}',
            "NaN path": (ok % "NaN").encode(),
            "Infinity path": (ok % "Infinity").encode(),
            "number path": (ok % "12345").encode(),
            "list path": (ok % '["C:/x"]').encode(),
            "null path": (ok % "null").encode(),
            "dict path": (ok % '{"a": 1}').encode(),
            "bool path": (ok % "true").encode(),
            "huge int schema": b'{"schema": ' + b"9" * 5000 + b', "repo_path": "", "naver_profiles": {}}',
            "lone surrogate path": (ok % ('"' + BS + 'ud800"')).encode(),
            "nul path": (ok % ('"a' + BS + 'u0000b"')).encode(),
            "bom": bytes([0xEF, 0xBB, 0xBF]) + (ok % '""').encode(),
            "not utf8": bytes([0xFF, 0xFE, 0xFA]),
            "empty": b"",
            "json null": b"null",
            "text garbage": b"x" * 100_000,
            "unknown field": b'{"schema": 1, "repo_path": "", "naver_profiles": {}, "extra": 1}',
        }

    def test_every_adversarial_settings_file_is_refused_gracefully_before_anything_changes(self):
        for label, raw in self.payloads().items():
            with self.subTest(label=label):
                saved = (self.folder / "settings.json").read_bytes(), (self.folder / bf.MANIFEST_NAME).read_bytes()
                try:
                    self.forge_bytes("settings.json", raw)
                    self.assert_refused_before_anything_changed()
                finally:
                    (self.folder / "settings.json").write_bytes(saved[0])
                    (self.folder / bf.MANIFEST_NAME).write_bytes(saved[1])

    def test_a_settings_or_json_file_over_the_size_cap_is_refused_before_it_is_even_read(self):
        for name in ("settings.json", layout.SEEDS_FILE):
            with self.subTest(name=name):
                original = (self.folder / name).read_bytes(), (self.folder / bf.MANIFEST_NAME).read_bytes()
                try:
                    self.forge_bytes(name, original[0] + b" " * (bf.MAX_JSON_BYTES + 1 - len(original[0])))
                    real = bf._sha256_file
                    read = []

                    def watch(path):
                        read.append(Path(path).name)
                        return real(path)

                    with mock.patch.object(bf, "_sha256_file", watch):
                        error = self.assert_refused_before_anything_changed()
                    self.assertNotIn(name, read, "그 파일은 읽기 전에 거절했다")
                    self.assertIn("너무 크다", error.detail)
                    self.assertIn(name, error.detail)
                finally:
                    (self.folder / name).write_bytes(original[0])
                    (self.folder / bf.MANIFEST_NAME).write_bytes(original[1])

    def test_a_settings_file_exactly_at_the_cap_is_still_accepted(self):
        original = (self.folder / "settings.json").read_bytes()
        self.forge_bytes("settings.json", original + b" " * (bf.MAX_JSON_BYTES - len(original)))
        self.assertEqual(self.restore(self.outcome.row.name).status, bf.STATUS_COMPLETE)

    def test_the_cap_is_the_one_the_backup_side_already_uses(self):
        from chanceblog_desktop.topicdb.backup import MAX_JSON_BYTES
        self.assertEqual(bf.MAX_JSON_BYTES, MAX_JSON_BYTES)
        self.assertEqual(bf.MAX_JSON_BYTES, 8 * 1024 * 1024)


if __name__ == "__main__":
    unittest.main()
