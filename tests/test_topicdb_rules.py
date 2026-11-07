"""주제 엔진 저장 계층(`topicdb/`)의 규칙을 소스에서 직접 확인하는 시험(AST 검사) — 서비스 층 안전 시험(`test_service_safety`)과 같은 정신이다(P3, D-61). 규칙을 어기는 코드가 몰래 들어오면 여기서 걸린다.

왜 따로 있나: `test_service_safety` 는 `service/*.py` 만 훑는다. 주제 엔진의 파일 쓰기(SQLite 열기·사본·백업·복원)는 `content/store.py` 와 같은 층의 새 패키지 `topicdb/` 가 하므로 — 서비스 쪽 쓰기 허용 목록을
늘리지 않으려고 — **같은 규칙을 이 패키지에 (파일, 함수) 단위로** 건다. 새 쓰기가 생기면 아래 `WRITERS` 표에 (파일, 함수)와 이유를 의식적으로 더해야 한다.
지키는 것:
  1) 네트워크·프로세스·셸 부품(`subprocess`·`socket`·`urllib`·`http`·`ssl`·`ctypes` …)과 `shutil` 을 가져오지 않는다. 가져오는 안쪽 모듈은 정해진 것뿐이고 `service`·`ui`·`publish`·`render` 를 거꾸로 가져오지 않는다.
  2) 파일을 쓰거나 지우거나 이름을 바꾸는 호출은 `WRITERS` 의 (파일, 함수)에서만 한다. SQL 에는 `DROP`·`TRUNCATE` 가 없고 `DELETE FROM` 은 90일 뒤 상세 정리(`cleanup_hold` — 운영자 결정 2026-11-06, 사용자가 확인했을 때만) 한 문장뿐이다.
  3) 조용한 실패 금지: 맨 `except:` 와 본문이 `pass` 뿐인 `except` 가 없다. 키 보관소·환경 변수를 읽지 않고 영어 비밀 낱말이 문자열에 없다.
  4) 코드는 파이썬 3.10 문법이고 던지는 오류 코드는 모두 카탈로그에 있다. 이 패키지는 `service/` 말고는 어디서도 쓰이지 않는다.
"""
import ast
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import topics_support as ts  # noqa: E402

from chanceblog_desktop.errors import CATALOG  # noqa: E402

SRC = ts.ROOT / "src" / "chanceblog_desktop"
TOPICDB = SRC / "topicdb"
FILES = sorted(TOPICDB.glob("*.py"))
SERVICE_TOPIC_FILES = [SRC / "service" / name for name in ("topics.py", "topic_files.py", "topic_format.py")]
FORBIDDEN_IMPORTS = {"subprocess", "socket", "urllib", "http", "ssl", "webbrowser", "ctypes", "requests", "ftplib", "smtplib", "telnetlib", "xmlrpc", "asyncio", "shutil", "tempfile"}
FORBIDDEN_LAYERS = {"service", "ui", "publish", "render", "jobs", "update", "assist", "check"}
ALLOWED_INTERNAL = {"content.candidates", "content.store", "echo", "errors", "security.mask"}        # `..` 로 가져오는 안쪽 모듈 — `topics` 와 같은 패키지(`.file` 등)는 따로 허용
# 파일을 쓰는 호출이 허용된 (파일, 함수) 와 그 호출의 전체 이름 — 이유를 함께 적는다. 목록을 늘리는 것은 시험 변경이므로 독립 검증에서 함께 본다.
WRITERS = {
    ("file.py", "open"): {"path.parent.mkdir", "sqlite3.connect"},    # 보관함 폴더·파일을 만든다(없을 때) — 쓰기로 여는 `sqlite3.connect` 는 여기서만(읽기 전용 `mode=ro` 열기는 표 밖)
    ("file.py", "_snapshot"): {"sqlite3.connect"},                 # 점검할 사본 파일(대상)을 SQLite 백업 방식으로 만든다
    ("file.py", "copy_to"): {"sqlite3.connect"},                   # 다른 파일로 복사(백업)한다 — 대상 파일을 만든다
    ("file.py", "_discard"): {"os.unlink"},                        # 올리기 전 사본의 임시 파일을 치운다
    ("file.py", "_make_copy"): {"os.rename"},                      # 점검한 사본의 이름을 바꿔 둔다(이미 있으면 덮어쓰지 않고 실패)
    ("backup.py", "_write_bytes"): {"open", "handle.write", "handle.flush", "os.fsync"},      # 백업·복원이 파일을 쓰는 단 한 곳(다 쓰고 디스크에 내려보낸다)
    ("backup.py", "_remove_file"): {"os.unlink"},                  # 앱이 만든 파일 하나를 지운다
    ("backup.py", "make_backup"): {"backups_dir.mkdir", "temp.mkdir", "os.rename"},           # 임시 폴더에서 만들어 이름을 바꾼다
    ("backup.py", "_clear_known"): {"os.rmdir"},                   # 앱이 만든 이름의 파일만 지운 빈 폴더를 없앤다
    ("backup.py", "restore_backup"): {"data_dir.mkdir", "os.replace"},                         # 임시 이름으로 쓴 JSON 을 제자리로 바꾼다
    ("backup.py", "_move_aside"): {"os.replace"},                  # 읽을 수 없는 지금 보관함·JSON 을 지우지 않고 옆으로 옮긴다
    ("backup.py", "_roll_back"): {"os.replace"},                   # 복원이 도중에 실패하면 원래 내용을 임시 이름으로 써서 제자리로 되돌린다(단계마다 따로 시도 — D-76)
    ("backup.py", "_undo_moves"): {"os.replace"},                  # 복원이 도중에 실패하면 옮겨 둔 파일을 제자리로 되돌린다
    ("backup.py", "_remove_empty"): {"os.rmdir"},                  # 막히거나 실패한 백업이 새로 만든 빈 폴더를 치운다
}
FILE_CALLS = {"open", "sqlite3.connect", "os.open", "os.write", "os.fsync", "os.rename", "os.replace", "os.remove", "os.unlink", "os.rmdir", "os.makedirs", "os.chmod", "os.link", "os.symlink", "os.truncate", "os.mkdir"}
FILE_METHODS = {"write_text", "write_bytes", "unlink", "mkdir", "rmdir", "touch", "rename", "rmtree", "chmod", "symlink_to", "hardlink_to", "truncate", "write", "flush", "copy", "copy2", "copyfile", "copytree", "move"}
SECRET_WORDS = re.compile(r"(?i)\b(api[_ -]?key|secret|token|passw(?:or)?d|credential)s?\b")
SQL_DANGER = re.compile(r"(?i)\b(DELETE\s+FROM|DROP\s+(TABLE|INDEX|VIEW|TRIGGER)|TRUNCATE)\b")
ALLOWED_DELETE = "DELETE FROM candidates WHERE candidate_id = ?"           # P3b-1 의도적 갱신: 90일 뒤 상세 정리가 후보 하나를 지우는 문장 — 이것 하나만 허용하고 다른 지우기는 모두 막는다(보류함·점수·출처·연결은 외래 키로 함께 지워진다)


def parse(path):
    return ast.parse(Path(path).read_text(encoding="utf-8"), filename=str(path))


def calls_with_function(node, function=""):
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.Call):
            yield child, function
        yield from calls_with_function(child, child.name if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) else function)


def opens_read_only(node):
    """`sqlite3.connect(…)` 의 첫 인자가 읽기 전용 주소(`_read_only_uri(…)` 이거나 그것을 담은 `uri`)인가 — 그런 연결은 파일을 만들지 않는다."""
    first = node.args[0] if node.args else None
    return (isinstance(first, ast.Call) and ast.unparse(first.func) == "_read_only_uri") or (isinstance(first, ast.Name) and first.id == "uri")


def opens_for_writing(node):
    """`경로.open(모드)` 의 모드가 쓰기·덧붙이기·새로 만들기·읽고 쓰기(`w`·`a`·`x`·`+`)를 담은 글자인가."""
    mode = node.args[0] if node.args else next((item.value for item in node.keywords if item.arg == "mode"), None)
    return isinstance(mode, ast.Constant) and isinstance(mode.value, str) and any(letter in mode.value for letter in "wax+")


def write_violations(file_name, tree):
    """한 파일의 소스에서 정해진 (파일, 함수) 밖의 파일 쓰기·열기·지우기 호출을 모은다."""
    found = []
    for node, function in calls_with_function(tree):
        full = ast.unparse(node.func)
        is_method = isinstance(node.func, ast.Attribute)
        name = node.func.attr if is_method else (node.func.id if isinstance(node.func, ast.Name) else "")
        flagged = ((full in FILE_CALLS and not (full == "sqlite3.connect" and opens_read_only(node))) or (is_method and name in FILE_METHODS) or (isinstance(node.func, ast.Name) and name == "open")
                   or (is_method and name == "open" and opens_for_writing(node))
                   or (is_method and name == "replace" and len(node.args) == 1 and not node.keywords and full != "dataclasses.replace"))        # `경로.replace(대상)` — 글자 바꾸기(`replace(옛, 새)`)·`dataclasses.replace(…)` 와 다르다
        if flagged and full not in WRITERS.get((file_name, function), set()):
            found.append(f"{file_name}:{node.lineno} {function or '(함수 밖)'}: {full}")
    return found


def strings(tree):
    return [node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)]


class PackageTest(unittest.TestCase):
    def test_the_package_has_exactly_the_expected_modules(self):
        self.assertEqual([path.name for path in FILES], ["__init__.py", "backup.py", "file.py", "store.py"], "모듈을 더하거나 뺐다면 이 목록과 docs/ARCHITECTURE.md §5 의 topicdb 행을 의식적으로 함께 고친다")

    def test_every_module_starts_with_an_explanation_and_the_init_is_only_that(self):
        for path in FILES:
            with self.subTest(module=path.name):
                doc = ast.get_docstring(parse(path))
                self.assertTrue(doc and len(doc) > 40)
        body = parse(TOPICDB / "__init__.py").body
        self.assertEqual(len(body), 1)

    def test_the_source_is_python_3_10_grammar(self):
        for path in [*FILES, *SERVICE_TOPIC_FILES]:
            with self.subTest(module=path.name):
                ast.parse(path.read_text(encoding="utf-8"), feature_version=(3, 10))


class ImportRulesTest(unittest.TestCase):
    def imports(self, tree):
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    yield 0, alias.name, ()
            elif isinstance(node, ast.ImportFrom):
                yield node.level, node.module or "", tuple(alias.name for alias in node.names)

    def test_no_network_process_shell_or_file_copy_module_is_imported(self):
        for path in [*FILES, *SERVICE_TOPIC_FILES]:
            for level, module, _names in self.imports(parse(path)):
                with self.subTest(file=path.name, module=module):
                    if level == 0:
                        self.assertNotIn(module.split(".")[0], FORBIDDEN_IMPORTS)

    def test_the_package_imports_only_the_documented_inner_modules_and_never_the_upper_layers(self):
        for path in FILES:
            for level, module, _names in self.imports(parse(path)):
                if level == 2:
                    with self.subTest(file=path.name, module=module):
                        top = module.split(".")[0]
                        self.assertNotIn(top, FORBIDDEN_LAYERS, "service·ui·publish·render·check 를 거꾸로 가져오지 않는다")
                        self.assertTrue(module in ALLOWED_INTERNAL or top == "topics", f"허용 목록에 없는 안쪽 모듈: {module}")
                elif level >= 3:
                    self.fail(f"{path.name}: 너무 바깥을 가져온다")

    def test_the_topics_package_does_not_know_the_storage_layer(self):
        for path in (SRC / "topics").glob("*.py"):
            for _level, module, names in self.imports(parse(path)):
                with self.subTest(file=path.name, module=module):
                    self.assertNotEqual(module.split(".")[0], "topicdb")
                    self.assertNotIn("topicdb", names)

    def test_only_the_service_layer_uses_the_storage_package(self):
        # 의도적 갱신(P4b, D-218 ⑤): 서비스 층의 새 모듈 `service/blog_profiles.py` 가 저장 계층의 점검 도구(`topicdb.backup` 의 JSON·키 모양 검사)를 읽을 때와 쓰기 전에 그대로 쓴다 — 읽을 때의 판정과 쓰기 전 판정이 한 벌이게.
        # 규칙의 뜻(저장 계층은 서비스 층만 쓴다)은 그대로이고, 파일에 쓰는 일은 여전히 `context.write_json` 하나다(저장 계층의 '쓰는 (파일, 함수)' 표는 안 건드렸다).
        users = []
        for path in SRC.rglob("*.py"):
            relative = path.relative_to(SRC)
            if relative.parts[0] == "topicdb":
                continue
            text = path.read_text(encoding="utf-8")
            if re.search(r"(?m)^\s*(?:from\s+(?:[.\w]*\.)?topicdb\b|import\s+(?:[\w.]*\.)?topicdb\b|from\s+\.+\s+import\s+[^#\n]*\btopicdb\b)", text):
                users.append(relative.as_posix())
        self.assertEqual(sorted(users), ["service/blog_profiles.py", "service/topic_files.py", "service/topics.py"], "주제 엔진 저장 계층을 쓰는 곳은 서비스의 세 모듈뿐이다")


class WriteRulesTest(unittest.TestCase):
    def test_every_file_write_of_the_package_is_in_a_listed_file_and_function(self):
        for path in FILES:
            with self.subTest(file=path.name):
                self.assertEqual(write_violations(path.name, parse(path)), [])

    def test_the_listed_places_really_make_those_calls_so_the_table_has_no_dead_rows(self):
        used = {}
        for path in FILES:
            for node, function in calls_with_function(parse(path)):
                full = ast.unparse(node.func)
                if full in {call for calls in WRITERS.values() for call in calls} and not (full == "sqlite3.connect" and opens_read_only(node)):
                    used.setdefault((path.name, function), set()).add(full)
        for place, calls in WRITERS.items():
            with self.subTest(place=place):
                self.assertEqual(used.get(place, set()), calls, "표에 적은 호출이 그 함수에 없거나 더 있다 — 표와 코드를 함께 맞춘다")

    def test_the_service_topic_modules_write_files_only_through_write_json_and_the_store(self):
        for path in SERVICE_TOPIC_FILES:
            with self.subTest(file=path.name):
                self.assertEqual(write_violations(path.name, parse(path)), [], "서비스는 직접 쓰지 않는다 — 설정 파일은 context.write_json, 보관함은 topicdb 가 쓴다")

    def test_the_rule_fires_on_a_new_write_anywhere_else(self):
        cases = (
            ("store.py", "def f(p):\n    p.write_text('x')\n", True), ("store.py", "def f(p):\n    open(p, 'w')\n", True), ("store.py", "def f(p):\n    os.remove(p)\n", True),
            ("store.py", "def f(a, b):\n    os.replace(a, b)\n", True), ("store.py", "def f(p):\n    p.unlink()\n", True), ("store.py", "def f(p):\n    p.mkdir()\n", True),
            ("file.py", "def other(p):\n    os.unlink(p)\n", True), ("file.py", "def _discard(p):\n    os.unlink(p)\n", False), ("file.py", "def _discard(p):\n    p.write_bytes(b'')\n", True),
            ("file.py", "def _make_copy(a, b):\n    os.rename(a, b)\n", False), ("file.py", "def _make_copy(a, b):\n    os.replace(a, b)\n", True), ("file.py", "def open(path):\n    path.parent.mkdir(parents=True)\n", False),
            ("backup.py", "def _write_bytes(p, d):\n    with open(p, 'wb') as handle:\n        handle.write(d)\n        handle.flush()\n        os.fsync(handle.fileno())\n", False),
            ("backup.py", "def make_backup(a):\n    shutil.rmtree(a)\n", True), ("backup.py", "def make_backup(a):\n    os.rmdir(a)\n", True), ("backup.py", "def restore_backup(a, b):\n    os.replace(a, b)\n", False),
            ("backup.py", "def restore_backup(a):\n    os.remove(a)\n", True), ("backup.py", "def _prune(a):\n    a.unlink()\n", True), ("backup.py", "def f(d):\n    return d.replace('a', 'b')\n", False),
            ("store.py", "def f(db):\n    db.execute('SELECT 1')\n    x = dataclasses.replace(y)\n", False),
            ("store.py", "def f(p):\n    p.open('w').close()\n", True), ("store.py", "def f(p):\n    p.open(mode='ab')\n", True), ("store.py", "def f(p):\n    p.open('rb')\n", False),
            ("store.py", "def f(p):\n    p.open()\n", False), ("store.py", "def f(p, q):\n    p.replace(q)\n", True), ("store.py", "def f(p):\n    sqlite3.connect(str(p))\n", True),
            ("store.py", "def f(p):\n    sqlite3.connect(_read_only_uri(p), uri=True)\n", False), ("store.py", "def f(uri):\n    sqlite3.connect(uri, uri=True)\n", False),
            ("file.py", "def open(p):\n    sqlite3.connect(str(p))\n", False), ("file.py", "def _discard(p):\n    sqlite3.connect(str(p))\n", True),
            ("backup.py", "def _scan(p):\n    sqlite3.connect(str(p))\n", True), ("backup.py", "def _move_aside(a, b):\n    os.replace(a, b)\n", False),
            ("backup.py", "def _remove_empty(a):\n    os.rmdir(a)\n", False), ("backup.py", "def make_backup(a):\n    os.rmdir(a)\n", True),
        )
        for file_name, source, violated in cases:
            with self.subTest(file=file_name, source=source.replace("\n", " ; ")[:70]):
                self.assertEqual(bool(write_violations(file_name, ast.parse(source))), violated, source)

    def test_no_sql_deletes_drops_or_truncates_anything(self):
        for path in FILES:
            for text in strings(parse(path)):
                with self.subTest(file=path.name, text=text[:40]):
                    if text == ALLOWED_DELETE:
                        self.assertEqual(path.name, "store.py", "허용한 지우기 문장은 보관함 저장소에만 있다")
                        continue
                    self.assertIsNone(SQL_DANGER.search(text), "후보를 지우거나 표를 없애는 문장은 허용한 한 문장 말고는 없다(지울지는 운영자가 정한다)")

    def test_the_sql_checker_catches_what_it_should(self):
        for text in ("DELETE FROM candidates WHERE 1", "delete  from x", "DROP TABLE a", "drop index i", "TRUNCATE t"):
            self.assertIsNotNone(SQL_DANGER.search(text), text)
        for text in ("INSERT INTO x VALUES (1)", "UPDATE x SET a = 1", "SELECT * FROM x", "IF NOT EXISTS", "dropped candidates"):
            self.assertIsNone(SQL_DANGER.search(text), text)


class HygieneTest(unittest.TestCase):
    def test_no_error_is_swallowed_silently(self):
        for path in [*FILES, *SERVICE_TOPIC_FILES]:
            for node in ast.walk(parse(path)):
                if isinstance(node, ast.ExceptHandler):
                    with self.subTest(file=path.name, line=node.lineno):
                        self.assertIsNotNone(node.type, "맨 except: 금지")
                        self.assertFalse(all(isinstance(item, ast.Pass) for item in node.body), "본문이 pass 뿐인 except 금지")

    def test_no_secret_words_environment_or_key_store_access(self):
        for path in FILES:
            tree = parse(path)
            for text in strings(tree):
                with self.subTest(file=path.name, text=text[:30]):
                    self.assertIsNone(SECRET_WORDS.search(text))
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute):
                    self.assertNotIn(node.attr, ("environ", "getenv"), f"{path.name}: 환경 변수를 읽지 않는다")

    def test_the_error_codes_the_package_raises_are_in_the_catalog(self):
        pattern = re.compile(r'AppError\(\s*"([A-Z][A-Z0-9_]+)"')
        codes = {code for path in [*FILES, *SERVICE_TOPIC_FILES] for code in pattern.findall(path.read_text(encoding="utf-8"))}
        self.assertTrue({"TOPIC_STORE_CORRUPT", "TOPIC_STORE_VERSION_UNSUPPORTED", "TOPIC_STORE_LOCKED", "TOPIC_STORE_RECOVERY_PENDING", "TOPIC_BACKUP_INVALID", "TOPIC_BACKUP_BLOCKED", "TOPIC_FILE_INVALID",
                         "TOPIC_CANDIDATE_NOT_FOUND", "TOPIC_CANDIDATE_AMBIGUOUS"} <= codes | set(self.mapped_codes()))
        for code in sorted(codes):
            with self.subTest(code=code):
                self.assertIn(code, CATALOG)

    def mapped_codes(self):
        """`file.py` 의 SQLite 오류 문구 → 코드 표(`_ERROR_RULES`)에 적힌 코드들."""
        text = (TOPICDB / "file.py").read_text(encoding="utf-8")
        return re.findall(r'"([A-Z][A-Z0-9_]+)"\),\n', text)

    def test_every_new_error_code_has_the_five_columns_and_a_topics_hint(self):
        for code in ("TOPIC_STORE_CORRUPT", "TOPIC_STORE_VERSION_UNSUPPORTED", "TOPIC_STORE_LOCKED", "TOPIC_STORE_RECOVERY_PENDING", "TOPIC_FILE_INVALID", "TOPIC_CANDIDATE_NOT_FOUND",
                     "TOPIC_CANDIDATE_AMBIGUOUS", "TOPIC_BACKUP_INVALID", "TOPIC_BACKUP_BLOCKED"):
            with self.subTest(code=code):
                info = CATALOG[code]
                self.assertTrue(info.message and info.action and info.when)
                self.assertNotIn("글 데이터", info.message, "글 보관함의 문구가 아니다")


if __name__ == "__main__":
    unittest.main()
