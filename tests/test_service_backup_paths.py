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
        "C:" + BS + "a b" + BS + "c", "relative" + BS + "path", "C:/x", "a" * bf.MAX_REPO_PATH, "C:" + BS + "x:y", "x:" + BS + "y")
BAD = {
    "network": (BS * 2 + HOST + BS + "share" + BS + "repo", "//" + HOST + "/share/repo", BS * 2 + "?" + BS + "C:" + BS + "x", BS * 2 + "." + BS + "pipe" + BS + "x", "/" + BS + HOST + BS + "x",
                BS + "/" + HOST + "/x", BS * 3 + HOST),
    "url": ("https://" + HOST + "/x", "file:///C:/x", "ftp://" + HOST + "/y", "C:/x://y", "smb://" + HOST + "/s"),
    "control": ("C:" + BS + "x" + chr(10) + "y", "C:/x" + chr(0) + "y", "C:/x" + chr(0x202E) + "y", "C:/x" + chr(0x200B), "C:/x" + chr(0x2028), chr(7) + "C:/x", "C:/x" + chr(0x7F), "C:/x" + chr(0xE000), "C:/x" + chr(0x2029), "C:/x" + chr(0x0378)),
    "length": ("C:/" + "a" * 1100, "a" * (bf.MAX_REPO_PATH + 1)),
}


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
