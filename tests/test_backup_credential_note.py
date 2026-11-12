"""백업이 '키(Credential)는 들어 있지 않다'고 사실대로 알린다(PCSEC1 M4 — 운영자 요청 4항 'Backup Manifest 에 Credential 제외됨을 명시').

범위는 **문구와 목록뿐**이다 — 무엇을 백업에 담는지는 바꾸지 않는다:
  1) 주제 엔진 백업의 목록 파일(`MANIFEST.json`)에 `credential_excluded: true` 와 쉬운 문장이 적힌다. 옛 백업(그 두 칸이 없는 목록)도 그대로 읽히고, 값이 틀리거나 모르는 칸이 더 있으면 거절한다.
  2) 명령줄 `backup`·`topics backup` 출력에 한 줄('키는 백업에 들어 있지 않아요 — 복원 뒤 다시 등록하세요')이 있고 `--json` 에 `credential_excluded` 가 있다.
  3) 백업 폴더 어디에도(목록 포함) 키 값이 없다 — 키를 등록해 둔 채 백업해 본다(가짜 보관소·카나리).
(글 보관함 백업 파일 `Store.backup` 의 짝 목록과 백업 화면은 이 묶음 밖이다.) 네트워크 없이 돈다.
"""
import hashlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import service_support as ss  # noqa: E402

from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.security.keystore import MemoryStore  # noqa: E402
from chanceblog_desktop.service import cli  # noqa: E402
from chanceblog_desktop.service import connections as cn  # noqa: E402
from chanceblog_desktop.topicdb import backup as tbackup  # noqa: E402

LINE = "키는 백업에 들어 있지 않아요 — 복원 뒤 다시 등록하세요"
CANARY = "CANARY_BACKUP_" + hashlib.sha256(b"pcsec1-m4").hexdigest()[:24]


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.store = MemoryStore()
        self.ctx = ss.make_ctx(self.tmp, repo=None)
        self.ctx.keystore = self.store
        cn.add_entry(self.ctx, "ai_assist", name="기본", fields={"key": CANARY}, provider="gemini", keystore=self.store)       # 키를 등록해 둔 채 백업한다

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        code = cli.main(list(argv), out=out, err=err, ctx=self.ctx, env={}, stdin=io.StringIO(""))
        return code, out.getvalue(), err.getvalue()

    def topic_backup(self):
        self.assertEqual(self.run_cli("topics", "init", "--yes")[0], 0)
        code, out, err = self.run_cli("--json", "topics", "backup")
        self.assertEqual(code, 0, err)
        return Path(json.loads(out)["data"]["backup"]), json.loads(out)["data"]


class TopicManifestTest(Base):
    def test_the_new_manifest_says_credentials_are_excluded_in_plain_korean(self):
        folder, data = self.topic_backup()
        manifest = json.loads((folder / "MANIFEST.json").read_text(encoding="utf-8"))
        self.assertIs(manifest["credential_excluded"], True)
        self.assertEqual(manifest["credential_excluded_note"], tbackup.CREDENTIAL_NOTE)
        self.assertIn("복원한 뒤 키는 다시 등록하세요", manifest["credential_excluded_note"])
        self.assertEqual(set(manifest), {"schema", "created_at", "files", "missing", "credential_excluded", "credential_excluded_note"})
        self.assertIs(data["credential_excluded"], True)
        tbackup.read_backup(folder)                                                           # 새 목록도 그대로 읽힌다

    def rewrite(self, folder, change):
        path = folder / "MANIFEST.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        change(manifest)
        path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def test_an_old_manifest_without_the_two_fields_is_still_readable(self):
        folder, _ = self.topic_backup()
        self.rewrite(folder, lambda manifest: (manifest.pop("credential_excluded"), manifest.pop("credential_excluded_note")))
        manifest, contents = tbackup.read_backup(folder)
        self.assertEqual(set(manifest), {"schema", "created_at", "files", "missing"})
        self.assertTrue(contents)

    def test_a_wrong_value_a_wrong_sentence_a_half_pair_and_an_unknown_field_are_refused(self):
        cases = {"거짓": lambda manifest: manifest.update(credential_excluded=False), "글": lambda manifest: manifest.update(credential_excluded="true"),
                 "다른 문장": lambda manifest: manifest.update(credential_excluded_note="키가 들어 있어요"), "한 칸만": lambda manifest: manifest.pop("credential_excluded_note"),
                 "모르는 칸": lambda manifest: manifest.update(extra="x")}
        for label, change in cases.items():
            with self.subTest(label=label):
                folder, _ = self.topic_backup()
                self.rewrite(folder, change)
                with self.assertRaises(AppError) as caught:
                    tbackup.read_backup(folder)
                self.assertEqual(caught.exception.code, "TOPIC_BACKUP_INVALID")

    def test_no_file_of_the_backup_holds_the_registered_key(self):
        folder, _ = self.topic_backup()
        for path in folder.rglob("*"):
            if path.is_file():
                data = path.read_bytes()
                self.assertFalse(CANARY.encode("utf-8") in data, path.name)                  # 값이 든 실패 글을 찍지 않으려고 assertFalse 로 본다
                self.assertFalse(CANARY.encode("utf-16-le") in data, path.name)


class CommandLineTest(Base):
    def test_both_backup_commands_say_the_key_is_not_in_the_backup(self):
        code, out, err = self.run_cli("backup")
        self.assertEqual((code, err), (0, ""))
        self.assertIn(LINE, out)
        self.assertEqual(self.run_cli("topics", "init", "--yes")[0], 0)
        code, out, err = self.run_cli("topics", "backup")
        self.assertEqual((code, err), (0, ""))
        self.assertIn(LINE, out)
        self.assertIn("키·토큰은 어떤 경우에도 담지 않습니다", out)

    def test_the_json_outputs_say_it_too_and_the_store_backup_file_has_no_key(self):
        code, out, err = self.run_cli("--json", "backup")
        data = json.loads(out)["data"]
        self.assertIs(data["credential_excluded"], True)
        raw = Path(data["backup"]).read_bytes()
        self.assertFalse(CANARY.encode("utf-8") in raw)
        self.assertFalse(CANARY.encode("utf-16-le") in raw)


if __name__ == "__main__":
    unittest.main()
