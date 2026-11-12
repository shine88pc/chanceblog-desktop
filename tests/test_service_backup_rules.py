"""전체 백업·복원(`service/backup_flow.py`)의 소스 규칙 시험 — 규칙을 어기는 코드가 몰래 들어오면 여기서 걸린다(AST 검사·합성 소스). 서비스 안전 시험(`test_service_safety`)과 같은 정신이다(BACKUPUI, D-380–D-399).

지키는 것:
  1) 네트워크·하위 프로세스·셸·`ctypes` 를 가져오지 않고, `os.system`·`os.popen`·`os.startfile`·`os.spawn…`·`os.exec…` 도 쓰지 않는다(폴더 열기 단추 같은 새 외부 호출 0).
  2) 파일을 만들고 옮기고 지우는 곳은 `test_service_safety` 가 허용한 (파일, 함수) 열 곳뿐이고, 허용한 호출이 그 함수에 실제로 있다(죽은 허용 줄 없음). 합성 소스로 '다른 함수의 새 쓰기' 가 걸리는지 본다.
  3) 키 보관소·환경 변수·연결 설정(`connections`)·로그·출력을 쓰지 않는다 — 이 코드는 키를 읽을 수 없다. `Store.backup`·`make_backup`(짝 파일을 더하는 기존 백업 길)을 부르지 않는다.
  4) 던지는 오류 코드는 모두 카탈로그에 있고, 목록 파일의 칸·담는 파일 이름·담지 않는 것의 이름이 문서·`security/backup_note.py` 와 맞는다. 3.10 문법이다.
  5) 백업·복원의 잠금은 이 PC 의 이름을 읽지 않는다(윈도 첫 호출이 하위 프로세스를 부른다).
"""
import ast
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import service_support as ss  # noqa: E402
import test_service_safety as safety  # noqa: E402

from chanceblog_desktop.errors import CATALOG  # noqa: E402
from chanceblog_desktop.security import backup_note  # noqa: E402
from chanceblog_desktop.service import backup_flow as bf  # noqa: E402
from chanceblog_desktop.service.lock import PublishLock  # noqa: E402
from chanceblog_desktop.topics import layout  # noqa: E402

SOURCE = ss.ROOT / "src" / "chanceblog_desktop" / "service" / "backup_flow.py"
NOTE = ss.ROOT / "src" / "chanceblog_desktop" / "security" / "backup_note.py"
WRITERS = {("_make_folder", "mkdir"), ("_remove_file", "unlink"), ("_remove_known_folder", "unlink"), ("_remove_known_folder", "rmdir"), ("_remove_empty", "rmdir"), ("_finish_folder", "rename"),
           ("_swap_in", "replace"), ("_move_aside", "replace"), ("_put_back", "replace")}


def tree():
    return ast.parse(SOURCE.read_text(encoding="utf-8"), filename=str(SOURCE))


def names_used(root, *, modules=True):
    """소스에 나오는 이름 — 변수·함수 이름, `.속성` 이름, 가져온 이름(`modules` 가 참이면 가져오는 모듈 이름도)."""
    found = {node.id for node in ast.walk(root) if isinstance(node, ast.Name)} | {node.attr for node in ast.walk(root) if isinstance(node, ast.Attribute)}
    found |= {alias.name.split(".")[-1] for node in ast.walk(root) if isinstance(node, (ast.Import, ast.ImportFrom)) for alias in node.names}
    if modules:
        found |= {(node.module or "").split(".")[-1] for node in ast.walk(root) if isinstance(node, ast.ImportFrom)}
    return found


class ImportAndCallRulesTest(unittest.TestCase):
    def test_no_network_process_shell_or_native_library_is_imported(self):
        for node in ast.walk(tree()):
            names = [alias.name for alias in node.names] if isinstance(node, ast.Import) else ([node.module or ""] if isinstance(node, ast.ImportFrom) and node.level == 0 else [])
            for name in names:
                with self.subTest(module=name):
                    self.assertNotIn(name.split(".")[0], safety.FORBIDDEN_IMPORTS)

    def test_no_call_starts_a_program_opens_a_viewer_or_a_shell(self):
        banned = {"system", "popen", "startfile", "spawnl", "spawnv", "spawnle", "spawnlp", "spawnve", "execl", "execv", "execle", "execlp", "execve", "Popen", "run", "check_output", "call", "urlopen", "open_new",
                  "reveal", "explorer"}
        used = names_used(tree())
        self.assertEqual(sorted(used & banned), [])
        for word in ("webbrowser", "subprocess", "socket", "urllib", "http", "startfile"):
            self.assertNotIn(word, used)

    def test_the_code_cannot_reach_keys_environment_connections_logs_or_prints(self):
        used = names_used(tree())
        for name in ("environ", "getenv", "keystore", "get_keystore", "default_keystore", "KeyStore", "connections", "logging", "print", "getLogger", "stderr", "stdout"):
            self.assertNotIn(name, used, name)

    def test_the_older_backup_paths_with_their_pair_files_are_not_used(self):
        used = names_used(tree(), modules=False)
        for name in ("make_backup", "backup_store", "backup_topics", "_copy_to", "copy_to", "restore_backup", "restore_store", "restore_topics"):
            self.assertNotIn(name, used, f"{name}: 짝 파일을 더하는 기존 백업 길을 이 폴더에 쓰지 않는다(D-383)")
        for node in ast.walk(tree()):
            if isinstance(node, ast.Attribute) and node.attr == "backup":
                self.assertNotIn(ast.unparse(node.value), ("Store", "store", "self"), "`Store.backup` 을 부르지 않는다 — SQLite 백업 API(`연결.backup`)를 직접 쓴다")

    def test_the_scanner_is_the_one_new_shared_scanner_and_the_older_shape_check_is_not_used(self):
        used = names_used(tree())
        self.assertIn("scan_secrets", used)
        self.assertIn("summarize", used)
        for name in ("has_key_shape", "scan_key_shape", "looks_secret", "mask"):
            self.assertNotIn(name, used, name)

    def test_the_source_is_python_3_10_grammar(self):
        ast.parse(SOURCE.read_text(encoding="utf-8"), feature_version=(3, 10))
        ast.parse(NOTE.read_text(encoding="utf-8"), feature_version=(3, 10))

    def test_the_flow_lock_does_not_read_the_name_of_this_pc(self):
        text = SOURCE.read_text(encoding="utf-8")
        self.assertIn('_FlowLock(ctx.workspace.locks_dir, LOCK_NAME, now=ctx.now, host="")', text)
        self.assertNotIn("platform", names_used(tree()))

    def test_the_copy_is_cleaned_with_a_vacuum_whose_temporary_copy_stays_in_memory(self):
        """D-398 — 사본의 빈 쪽(지운 글의 조각)을 `vacuum` 으로 정리하되, 그 동안의 임시 사본이 시스템 임시 폴더에 파일로 남지 않게 먼저 메모리로 돌린다. 순서: 백업 → 임시 저장소 설정 → 정리."""
        function = next(node for node in ast.walk(tree()) if isinstance(node, ast.FunctionDef) and node.name == "_stage_sqlite")
        calls = sorted((node.lineno, node.func.attr, [arg.value for arg in node.args if isinstance(arg, ast.Constant)]) for node in ast.walk(function)
                       if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in ("backup", "execute"))
        self.assertEqual([attr for _line, attr, _args in calls], ["backup", "execute", "execute"])
        self.assertEqual([args for _line, _attr, args in calls][1:], [["pragma temp_store = memory"], ["vacuum"]])


class WriteRulesTest(unittest.TestCase):
    def test_the_service_safety_rules_pass_for_this_file(self):
        self.assertEqual(safety.write_violations("backup_flow.py", tree()), [])

    def test_the_registered_writers_really_make_those_calls_so_the_table_has_no_dead_rows(self):
        registered = {key for key in safety.FILE_WRITERS if key[0] == "backup_flow.py"}
        self.assertEqual({name for _, name in registered}, {"_make_folder", "_remove_file", "_remove_known_folder", "_remove_empty", "_finish_folder"})
        found = set()
        for function in [node for node in ast.walk(tree()) if isinstance(node, ast.FunctionDef)]:
            for node in ast.walk(function):
                if isinstance(node, ast.Call):
                    full = ast.unparse(node.func)
                    name = node.func.attr if isinstance(node.func, ast.Attribute) else (node.func.id if isinstance(node.func, ast.Name) else "")
                    if name in {"mkdir", "unlink", "rmdir", "rename"} or full == "os.replace":              # `replace` 는 글자 바꾸기(`str.replace`)와 구별하려고 `os.replace` 만 센다
                        found.add((function.name, "replace" if full == "os.replace" else name))
        self.assertEqual(found, WRITERS, "표에 적은 호출이 그 함수에 없거나 더 있다 — 표와 코드를 함께 맞춘다")
        self.assertEqual({key for key in safety.OS_CALLS["os.replace"] if key[0] == "backup_flow.py"}, {("backup_flow.py", "_swap_in"), ("backup_flow.py", "_move_aside"), ("backup_flow.py", "_put_back")})
        self.assertEqual(safety.OS_CALLS["os.rename"], {("backup_flow.py", "_finish_folder")})

    def test_a_new_write_anywhere_else_in_the_file_is_caught_and_the_listed_ones_are_not(self):
        cases = (
            ("def other(p):\n    p.mkdir()\n", True), ("def _make_folder(p):\n    p.mkdir()\n", False), ("def other(p):\n    p.unlink()\n", True), ("def _remove_file(p):\n    os.unlink(p)\n", False),
            ("def other(p):\n    os.unlink(p)\n", True), ("def _remove_known_folder(f):\n    os.unlink(f)\n    os.rmdir(f)\n", False), ("def other(f):\n    os.rmdir(f)\n", True), ("def _remove_empty(f):\n    os.rmdir(f)\n", False),
            ("def other(a, b):\n    os.replace(a, b)\n", True), ("def _swap_in(a, b):\n    os.replace(a, b)\n", False), ("def _move_aside(a, b):\n    os.replace(a, b)\n", False), ("def _put_back(a, b):\n    os.replace(a, b)\n", False),
            ("def other(a, b):\n    os.rename(a, b)\n", True), ("def _finish_folder(a, b):\n    os.rename(a, b)\n", False), ("def _swap_in(a, b):\n    os.rename(a, b)\n", True),
            ("def other(p):\n    p.write_bytes(b'')\n", True), ("def other(p):\n    p.write_text('x')\n", True), ("def other(p):\n    open(p, 'wb')\n", True), ("def other(p):\n    open(p, 'rb')\n", True),
            ("def other(p):\n    shutil.rmtree(p)\n", True), ("def other(a, b):\n    shutil.copytree(a, b)\n", True), ("def other(p):\n    os.makedirs(p)\n", True), ("def other(p):\n    os.remove(p)\n", True),
            ("def other(p):\n    os.open(p, 0)\n", True), ("def other(fd):\n    os.write(fd, b'')\n", True), ("def other(fd):\n    os.fsync(fd)\n", True), ("def other(p):\n    p.touch()\n", True), ("def other(p):\n    p.chmod(0)\n", True),
            ("def _swap_in(a, b):\n    os.replace(a, b)\n    a.unlink()\n", True), ("def _make_folder(p):\n    p.mkdir()\n    p.rmdir()\n", True),
        )
        for source, violated in cases:
            with self.subTest(source=source.replace("\n", " ; ")[:70]):
                self.assertEqual(bool(safety.write_violations("backup_flow.py", ast.parse(source))), violated, source)

    def test_file_contents_are_written_only_through_the_durable_writer_of_the_context(self):
        calls = [node for node in ast.walk(tree()) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_write_durably"]
        self.assertGreaterEqual(len(calls), 4)
        text = SOURCE.read_text(encoding="utf-8")
        self.assertIn("from .context import Settings, _write_durably", text)


class CatalogAndNamesTest(unittest.TestCase):
    def test_every_error_code_the_file_names_is_in_the_catalog(self):
        text = SOURCE.read_text(encoding="utf-8")
        codes = set(re.findall(r'(?:AppError|FlowError)\(\s*"([A-Z][A-Z0-9_]+)"', text))
        codes |= set(re.findall(r'raise AppError\(locked_code', text) and ["STORE_LOCKED", "TOPIC_STORE_LOCKED"])
        self.assertTrue({"FULL_BACKUP_BLOCKED", "FULL_BACKUP_INVALID", "RESTORE_FAILED", "BACKUP_FAILED", "CONTENT_NOT_FOUND", "STORE_VERSION_UNSUPPORTED", "DISK_FULL", "FILE_WRITE_FAILED"} <= codes, codes)
        for code in sorted(codes):
            with self.subTest(code=code):
                self.assertIn(code, CATALOG)
        for constant in (*bf.DAMAGED_CODE.values(), *bf.STORE_NEWER, *bf.STORE_BUSY, *bf.STORE_DAMAGED, *bf.RESTORE_KIND):
            self.assertIn(constant, CATALOG, constant)
        self.assertEqual(set(bf.RESTORE_KIND.values()) | {"other"}, set(bf.RESTORE_REASON))

    def test_the_manifest_fields_are_exactly_the_ones_the_writer_makes(self):
        import datetime
        manifest = bf._manifest_dict(datetime.datetime(2026, 11, 11, tzinfo=datetime.timezone.utc), "0.0.0", {"seeds.json": {"size": 1, "sha256": "0" * 64, "items": {"count": 0}}}, [], {})
        self.assertEqual(set(manifest), set(bf.MANIFEST_KEYS))
        self.assertEqual(bf._manifest_problem(manifest), "")

    def test_the_components_are_the_four_topic_files_plus_the_store_and_the_settings(self):
        self.assertEqual([item.name for item in bf.COMPONENTS], ["chanceblog.db", layout.ENGINE_DB_FILE, layout.CHANNEL_PROFILES_FILE, layout.SEEDS_FILE, layout.CALENDAR_FILE, "settings.json"])
        self.assertEqual(set(layout.USER_DATA_FILES) | {"chanceblog.db", "settings.json"}, {item.name for item in bf.COMPONENTS})
        self.assertEqual(set(bf.AREA), {item.name for item in bf.COMPONENTS})
        self.assertEqual(bf.KNOWN_FILES, {item.name for item in bf.COMPONENTS} | {bf.MANIFEST_NAME})

    def test_the_things_left_out_include_the_four_named_by_the_operator_with_a_reason_each(self):
        names = [name for name, _ in backup_note.EXCLUDED]
        for name in ("connections.json", "quota_state.json", "publish/", "locks/"):
            self.assertIn(name, names)
        self.assertTrue(all(len(reason) > 15 for _, reason in backup_note.EXCLUDED))
        self.assertEqual(len(set(names)), len(names))

    def test_the_credential_sentence_lives_outside_the_service_folder_so_the_service_stays_free_of_those_words(self):
        self.assertFalse(str(NOTE).replace("\\", "/").endswith("service/backup_note.py"))
        self.assertEqual(backup_note.CREDENTIAL_NOTE, "자격 증명(키·토큰·쿠키·세션)은 이 백업에 들어 있지 않아요 — 복원한 뒤 키는 다시 등록하세요")
        self.assertEqual(backup_note.SHORT_NOTE, "Credential 제외됨")
        pattern = re.compile(r"(?i)\b(api[_ -]?key|secret|token|passw(?:or)?d|credential)s?\b")
        for text in safety.strings(tree()):
            self.assertIsNone(pattern.search(text), text[:40])

    def test_the_note_module_has_nothing_to_import_but_a_read_only_mapping(self):
        imports = [node for node in ast.walk(ast.parse(NOTE.read_text(encoding="utf-8"))) if isinstance(node, (ast.Import, ast.ImportFrom))]
        self.assertEqual([ast.unparse(node) for node in imports], ["from types import MappingProxyType"])


class LockHostTest(unittest.TestCase):
    def test_the_lock_accepts_a_host_name_and_still_reads_the_pc_name_when_none_is_given(self):
        from unittest import mock
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(PublishLock(tmp, "abc", now=ss.Clock(), host="").host, "")
            self.assertEqual(PublishLock(tmp, "abc", now=ss.Clock(), host="내 PC").host, "내 PC")
            with mock.patch("chanceblog_desktop.service.lock.host_name", return_value="다른 PC"):                # PCSEC1 의 `host_name()` — `platform.node()` 는 윈도에서 하위 프로세스를 띄울 수 있어 쓰지 않는다
                self.assertEqual(PublishLock(tmp, "abc", now=ss.Clock()).host, "다른 PC")
            source = (ss.ROOT / "src" / "chanceblog_desktop" / "service" / "lock.py").read_text(encoding="utf-8")
            self.assertNotIn("platform.node()", source.replace("`platform.node()`", ""), "lock.py 가 `platform.node()` 를 부르면 Network Write 0 이 빨개진다")


class CredentialNoteTest(unittest.TestCase):
    """D6 — 전체 백업의 목록과 주제 백업의 목록(PCSEC1 M4)이 '자격 증명 제외' 를 **같은 칸 이름·같은 문장 한 상수**로 적는다."""

    def test_both_manifests_use_one_constant_and_the_same_field_names(self):
        from chanceblog_desktop.topicdb import backup as tbackup
        self.assertIs(tbackup.CREDENTIAL_NOTE, backup_note.CREDENTIAL_NOTE, "상수가 둘이다")
        self.assertEqual(bf.MANIFEST_KEYS & {"credential_excluded", "credential_excluded_note"}, {"credential_excluded", "credential_excluded_note"})
        self.assertNotIn("credential_note", bf.MANIFEST_KEYS)
        self.assertIn("credential_excluded_note", tbackup._MANIFEST_KEYS_NEW)

    def test_the_sentence_says_that_credentials_are_not_in_the_backup_and_to_register_again(self):
        self.assertIn("들어 있지 않아요", backup_note.CREDENTIAL_NOTE)
        self.assertIn("다시 등록하세요", backup_note.CREDENTIAL_NOTE)


class DocsPinTest(unittest.TestCase):
    """문서가 이 묶음의 결정·보안·구조를 실제로 담는다 — 결정 기록(D-380–D-399)은 번호마다 한 줄씩 순서대로 있고 줄마다 있어야 할 낱말이 있으며(다른 묶음의 번호나 전체 최댓값은 못박지 않는다),
    구조·보안·변경 이력에는 이 묶음의 줄이 있다. 물결표·웹 주소는 이 묶음의 행에 없다."""
    ROW_WORDS = {'D-380': ('backup_flow.py', '백업·복원', '설정 화면', '명령줄', 'T2'), 'D-381': ('full-', 'before-restore', 'MANIFEST.json', '열 개'), 'D-382': ('connections.json', '아홉', 'backup_note.py'), 'D-383': ('Store.backup', 'PCSEC1', '읽기 전용'), 'D-384': ('history_ledger', 'D-75', '무시하고 백업', '여섯'), 'D-385': ('settings.json', '바이트'), 'D-386': ('완료', '부분', '실패'), 'D-387': ('안전 사본', '원복', '.bad-'), 'D-388': ('PublishLock', 'host', 'BACKUP_IN_PROGRESS'), 'D-389': ('STORE_VERSION_UNSUPPORTED', 'schema'), 'D-390': ('FULL_BACKUP_BLOCKED', 'FULL_BACKUP_INVALID', 'BACKUP_IN_PROGRESS', 'RESTORE_FAILED'), 'D-391': ('backups_provider', '55개', 'FakeHomeProvider'), 'D-392': ('작업 스레드', '제자리', '10초'), 'D-393': ('복원하기', '처음 포커스는 취소'), 'D-394': ('폴더 열기', 'USB'), 'D-395': ('아홉 종류', '무시하고 백업'), 'D-396': ('홈이', '복원 직전 사본'), 'D-397': ('명령줄', 'topics backup'), 'D-398': ('vacuum', 'temp_store', 'secure_delete'), 'D-399': ('변이', '59', 'gc.collect', 'blogs_topic', '병합할 때 주의'), 'D-460': ('_prune', 'protect', 'moment', '미래'), 'D-461': ('메모리', 'vacuum', '_sweep_locked', 'os._exit'), 'D-462': ('WAL', '롤백 저널'), 'D-463': ('restore-in-progress.json', '안전 사본으로 되돌리기', '자동으로 되돌리지 않는 이유'), 'D-464': ('STORE_RECOVERY_PENDING', 'RETRY_TRIES', 'RETRY_WAIT'), 'D-465': ('gc.collect', 'test_ui_qt_seeds', '세 번'), 'D-466': ('V06', 'V22', 'schema: true', 'D12'), 'D-467': ('git apply --3way', 'credential_excluded_note', 'backups_adapter', 'display_text')}
    LINE_WORDS = {'docs/ARCHITECTURE.md': ('service/backup_flow.py', 'D-380', 'interrupted_restore', 'test_service_backup_interrupt'), 'docs/SECURITY.md': ('전체 백업·복원', 'vacuum', 'D-398', 'restore-in-progress.json', '수정 라운드'),
                  'CHANGELOG.md': ('backup_flow.py', 'D-380–D-399', 'FULL_BACKUP_BLOCKED', 'D-460–D-466'), 'docs/UI_STATES.md': ('멈춘 복원 안내', 'D-463'), 'docs/UI_COMPONENTS.md': ('revert_button', 'backup-revert')}

    def read(self, rel):
        return (ss.ROOT / rel).read_text(encoding="utf-8")

    def test_each_decision_row_exists_once_in_order_and_carries_its_own_words(self):
        text = self.read("docs/DECISIONS.md")
        rows = {}
        for number in self.ROW_WORDS:
            found = [line for line in text.splitlines() if line.startswith(f"| {number} |")]
            self.assertEqual(len(found), 1, f"{number} 행은 정확히 한 줄이어야 한다")
            rows[number] = found[0]
        positions = [text.index(f"| {number} |") for number in self.ROW_WORDS]
        self.assertEqual(positions, sorted(positions), "행은 번호 순서로 있어야 한다")
        self.assertLess(positions[-1], text.index("**D-130 범위 규칙표**"), "결정 행은 D-130 범위 규칙표 앞(본 표 안)에 있어야 한다 — 그 표를 세는 시험이 뒤의 표 줄을 여덟으로 못박는다")
        for number, words in self.ROW_WORDS.items():
            for word in words:
                self.assertIn(word, rows[number], f"{number} 행에 '{word}' 가 없다")
            self.assertEqual(len(rows[number].split("|")), 6, f"{number}: 표의 한 행은 칸이 넷(번호·날짜·결정·상태·근거)이어야 한다")
        joined = "\n".join(rows.values())
        self.assertNotIn(chr(126), joined)
        self.assertIsNone(re.search(r"(?i)(https?|ftp)://|www[.]", joined))

    def test_structure_security_and_changelog_have_this_bundles_lines(self):
        for rel, words in self.LINE_WORDS.items():
            body = self.read(rel)
            for word in words:
                self.assertIn(word, body, f"{rel} 에 '{word}' 가 없다")

    def test_the_photos_the_visual_qa_section_shows_are_in_the_repository(self):
        body = self.read("docs/UI_VISUAL_QA.md")
        shown = re.findall(r"\(images/ui/([^)]*backup_[^)]*[.]png)\)", body)
        self.assertGreaterEqual(len(shown), 20)
        for name in shown:
            self.assertTrue((ss.ROOT / "docs" / "images" / "ui" / name).is_file(), name)


if __name__ == "__main__":
    unittest.main()
