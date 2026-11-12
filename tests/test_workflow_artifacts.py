"""워크플로 산출물·비밀 출력 규칙 시험 — `.github/workflows/*.yml` 을 **읽기만** 한다(워크플로는 이 시험이 고치지 않는다 — 변경은 T3).

운영자 목록의 마지막 위치 '워크플로 산출물(artifact)'(PCSEC1 H1): 산출물로 올라간 파일은 저장소를 읽을 수 있는 사람에게 내려받아진다 — 시험 로그·데이터 폴더·`*.log` 에 비밀이 있으면 그대로 나간다.
지키는 것:
  1) `actions/upload-artifact`(와 `upload-pages-artifact`)를 쓰는 단계가 **있으면** 그 `path:` 는 허용 목록 `ALLOWED_UPLOAD_FILES`(파일 이름 네 모양: 패키지 압축 파일·`SHA256SUMS`·`PACKAGE_INFO.md`·`PACKAGE_INFO.json`)에만 있고
     시험 로그·데이터 폴더·`*.log`·시험 결과·`.env`·사용자 폴더·와일드카드 폴더를 올리지 않는다. 업로드가 없어도, 허용된 모양으로 있어도 이 규칙은 통과한다 — **더는 '업로드 0 개' 를 못박지 않는다**(PCKIT 독립 검증 D3).
     **새 업로드를 더하려면 이 목록과 결정(docs/DECISIONS.md D-344)을 같이 고친다** — 상수와 결정 기록이 맞는지는 아래 시험이 본다. '오늘 main 의 워크플로(`ci.yml`·`auto-pr.yml`)는 업로드가 없다' 는 사실은 따로 알리는 정보 점검이다(허용된 업로드가 생겨도 빨개지지 않는다).
  2) `${{ secrets.… }}` 는 `env:` 값에서만 쓴다(`run:` 본문에 끼우지 않는다 — 셸이 글을 다시 해석하지 않게). 비밀·토큰이 든 환경 변수(`secrets.…`·`github.token` 을 받은 이름)를 `echo`·`printf`·`cat`·`tee` 로 내지 않는다.
  3) `set -x`(실행 줄을 펼쳐 찍는다)·`env`·`printenv`·`export -p`(환경 전체를 찍는다)를 `run:` 에서 쓰지 않는다.
규칙 자체도 합성 워크플로로 시험한다(어기는 합성 예가 실제로 걸리는지).
"""
import fnmatch
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / ".github" / "workflows"

# 산출물로 올려도 되는 파일 — **이 상수 한 곳이 허용 목록의 전부다**(파일 이름의 모양 넷: 릴리스 패키지 미리보기의 압축 파일·해시 목록·패키지 정보 둘). 폴더 부분은 막지 않되 아래 금지 모양과 와일드카드 폴더는 걸러 낸다.
# 새 업로드를 더하려면 이 목록과 결정(docs/DECISIONS.md D-344)을 같이 고친다 — 아래 시험이 상수와 결정 기록이 맞는지 본다.
ALLOWED_UPLOAD_FILES = ("ChanceBlogDesktop-*-win64.zip", "SHA256SUMS", "PACKAGE_INFO.md", "PACKAGE_INFO.json")
CHANGE_RULE_SENTENCE = "새 업로드를 더하려면 이 목록과 결정을 같이 고친다"
# 오늘 main 에 있는 워크플로 — 이 둘이 업로드하지 않는다는 사실만 정보 점검으로 알린다(빨개지지 않는다).
NO_UPLOAD_WORKFLOWS = ("ci.yml", "auto-pr.yml")
FORBIDDEN_SEGMENTS = {"tests", "test", "logs", "log", "data", "backups", "appdata", "localappdata", "__pycache__", "users", "home", "..", "~", ".env"}      # 경로 조각(폴더·파일 이름) 하나가 이것이면 금지
FORBIDDEN_SEGMENT_PREFIXES = ("test-", "test_", "tests-", "log-", "logs-", "~")
FORBIDDEN_SUFFIXES = (".log", ".env", ".sqlite", ".db", ".bak", ".pyc", ".key", ".pem")
SECRET_ENV_SOURCE = re.compile(r"\$\{\{\s*(?:secrets\.[A-Za-z0-9_]+|github\.token)\s*\}\}")
OUTPUT_COMMANDS = ("echo", "printf", "cat", "tee")


def workflow_texts():
    return {path.name: path.read_text(encoding="utf-8") for path in sorted(WORKFLOWS.glob("*.y*ml"))}


def steps_of(text):
    """워크플로 글에서 단계(`steps:` 아래 `- ` 항목)들의 글 조각. PyYAML 없이 들여쓰기로 읽는다."""
    lines = text.splitlines()
    steps = []
    index = 0
    while index < len(lines):
        match = re.match(r"^(\s*)steps:\s*$", lines[index])
        index += 1
        if not match:
            continue
        base = len(match.group(1))
        current, item_indent = None, None
        while index < len(lines):
            line = lines[index]
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                indent = len(line) - len(line.lstrip())
                if indent <= base:
                    break
                if stripped.startswith("- ") and (item_indent is None or indent == item_indent):
                    item_indent = indent
                    if current is not None:
                        steps.append("\n".join(current))
                    current = [line]
                    index += 1
                    continue
            if current is not None:
                current.append(line)
            index += 1
        if current is not None:
            steps.append("\n".join(current))
    return steps


def uses_of(step):
    found = re.search(r"^\s*-?\s*uses:\s*([^\s#]+)", step, re.M)
    return found.group(1) if found else ""


def block_after(step, key):
    """`key:` 아래의 값 — 한 줄 값이거나 `|`·`>` 블록(더 들여쓴 줄들). 없으면 ''."""
    lines = step.splitlines()
    for index, line in enumerate(lines):
        match = re.match(rf"^(\s*)(?:-\s+)?{re.escape(key)}:\s*(.*)$", line)
        if not match:
            continue
        inline = match.group(2).strip()
        if inline and inline not in ("|", ">", "|-", ">-", "|+", ">+"):
            return inline
        base = len(match.group(1))
        body = []
        for follow in lines[index + 1:]:
            if follow.strip() and (len(follow) - len(follow.lstrip())) <= base:
                break
            body.append(follow)
        return "\n".join(body)
    return ""


def upload_paths(step):
    """업로드 단계의 `with: path:` 값에 적힌 경로들(줄마다 하나)."""
    value = block_after(step, "path")
    return [item.strip() for item in re.split(r"[\n,]", value) if item.strip() and not item.strip().startswith("#")]


def forbidden_reason(path):
    """경로가 시험 로그·데이터 폴더·로그 파일·절대 경로·사용자 폴더 모양이면 그 이유(아니면 '')."""
    normalized = path.replace("\\", "/")
    if normalized.startswith(("/", "~")) or re.match(r"^[A-Za-z]:", normalized):
        return "절대 경로·사용자 폴더 모양이다"
    for segment in (part for part in normalized.split("/") if part):
        lowered = segment.lower()
        if lowered in FORBIDDEN_SEGMENTS or lowered.startswith(FORBIDDEN_SEGMENT_PREFIXES) or lowered.endswith(FORBIDDEN_SUFFIXES):
            return "시험 로그·데이터 폴더·로그 파일 모양이다"
    return ""


UPLOAD_ACTION = re.compile(r"upload[\w-]*artifact")                 # actions/upload-artifact · actions/upload-pages-artifact


def upload_steps(text):
    """산출물을 올리는 단계(`uses:` 가 upload…artifact) → [(단계 번호, 단계 글)]."""
    return [(number, step) for number, step in enumerate(steps_of(text), start=1) if UPLOAD_ACTION.search(uses_of(step))]


def path_problem(path):
    """올리는 경로 하나가 금지 모양이거나 허용 목록(`ALLOWED_UPLOAD_FILES`)에 없으면 그 이유(아니면 '')."""
    reason = forbidden_reason(path)
    if reason:
        return reason
    directory, _, name = path.replace(chr(92), "/").rpartition("/")
    if any(mark in directory for mark in "*?["):
        return "폴더 부분에 와일드카드가 있어 어느 폴더든 올라갈 수 있다"
    if not any(fnmatch.fnmatchcase(name, shape) for shape in ALLOWED_UPLOAD_FILES):
        return "허용 목록(ALLOWED_UPLOAD_FILES 의 파일 이름 네 모양)에 없다"
    return ""


def artifact_problems(text):
    """업로드 단계마다 허용 목록 밖의 경로·금지 모양을 모은다 → [(단계 번호, 경로, 이유)]. 업로드가 없으면 빈 목록이다(없는 것은 문제가 아니다)."""
    problems = []
    for number, step in upload_steps(text):
        paths = upload_paths(step)
        if not paths:
            problems.append((number, "", "path 가 없다"))
        for path in paths:
            reason = path_problem(path)
            if reason:
                problems.append((number, path, reason))
    return problems


def upload_inventory(texts):
    """워크플로 파일마다 업로드 단계가 올리는 경로들 → {파일 이름: [경로, ...]}(업로드 단계가 없는 파일은 넣지 않는다)."""
    found = {}
    for name, text in texts.items():
        steps = upload_steps(text)
        if steps:
            found[name] = [path for _number, step in steps for path in upload_paths(step)]
    return found


def main_upload_notes(texts):
    """정보 점검 — 오늘 main 의 워크플로(`NO_UPLOAD_WORKFLOWS`)가 업로드를 하고 있으면 그 알림 글들(없으면 빈 목록).
    **알림일 뿐 실패가 아니다**: 허용된 업로드라면 정상이고, 허용 밖이면 `artifact_problems`(규칙 시험)가 따로 빨갛게 한다."""
    inventory = upload_inventory(texts)
    return [f"{name} 가 산출물을 올린다: {', '.join(inventory[name]) or '(path 없음)'}" for name in NO_UPLOAD_WORKFLOWS if name in inventory]


def secret_output_problems(text):
    """`secrets.…` 가 `env:` 밖에 있거나, 비밀 환경 변수를 내보내는 명령·환경 전체를 찍는 명령이 있는 줄들 → [(줄 번호, 이유)]."""
    problems = []
    lines = text.splitlines()
    secret_names = set()
    for number, line in enumerate(lines, start=1):
        if line.lstrip().startswith("#"):
            continue
        assign = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$", line)
        if SECRET_ENV_SOURCE.search(line):
            if assign and assign.group(2).strip().startswith("${{"):
                secret_names.add(assign.group(1))                         # `NAME: ${{ secrets.X }}` — env 로 받는 올바른 모양
            elif "run:" in line or not assign:
                problems.append((number, "`secrets.` 를 `run:` 본문·글 속에 끼웠다 — env 로만 넘긴다"))
    in_run, run_base = False, 0
    for number, line in enumerate(lines, start=1):
        stripped = line.strip()
        if re.match(r"^\s*(?:-\s+)?run:\s*", line):
            in_run, run_base = True, len(line) - len(line.lstrip())
            body = re.sub(r"^\s*(?:-\s+)?run:\s*", "", line).strip()                  # `run:` 뒤 같은 줄 값도 명령이다(`run: echo "$TOK"` — PCSEC1V D2)
            body = re.sub(r"^[|>][-+]?\s*(?:#.*)?$", "", body)                         # 블록 표시(`|`·`>`)만 있으면 명령은 아래 줄들이다
            if len(body) >= 2 and body[0] == body[-1] and body[0] in "\"'":
                body = body[1:-1]                                                      # `run: "echo $TOK"` 처럼 따옴표로 묶은 한 줄
            commands = [body] if body.strip() else []
        elif in_run and stripped and (len(line) - len(line.lstrip())) <= run_base:
            in_run, commands = False, []
        else:
            commands = [line] if in_run else []
        for command in commands:
            text_line = command.strip()
            if not text_line or text_line.startswith("#"):
                continue
            if re.search(r"(?:^|[;&|\s])set\s+(?:-[A-Za-z]*x|-o\s+xtrace)", text_line):
                problems.append((number, "`set -x` 는 실행 줄을 펼쳐 찍는다"))
            if re.match(r"^(?:env|printenv)(?:\s|$)", text_line) or re.search(r"(?:^|[;&|]\s*)(?:env|printenv|export\s+-p)(?:\s*[;&|]|\s*$)", text_line):
                problems.append((number, "환경 전체를 찍는 명령이다"))
            for part in re.split(r"\s*(?:&&|\|\||;|\|)\s*", text_line):                 # 명령 하나씩 — `test -n "$X" && echo 설정됨` 의 `$X` 는 echo 의 인자가 아니다
                if any(re.match(rf"^{command_name}\b", part.strip()) for command_name in OUTPUT_COMMANDS):
                    for name in secret_names:
                        if re.search(rf"\$\{{?{re.escape(name)}\b", part):
                            problems.append((number, f"비밀을 받은 환경 변수 {name} 를 내보낸다"))
    return problems


class ArtifactRuleTest(unittest.TestCase):
    def test_there_are_workflows_to_read(self):
        names = sorted(workflow_texts())
        self.assertIn("ci.yml", names)
        self.assertIn("auto-pr.yml", names)

    def test_every_upload_in_every_workflow_is_an_allowed_file_and_nothing_else(self):
        """업로드가 없으면 통과하고, 있으면 그 경로가 모두 허용 목록의 파일 모양이며 로그·데이터 폴더·시험 결과를 올리지 않아야 한다 — 업로드가 생기는 것 자체는 빨갛지 않다(PCKIT 독립 검증 D3)."""
        for name, text in workflow_texts().items():
            with self.subTest(workflow=name):
                self.assertEqual(artifact_problems(text), [], f"{name}: 허용 목록(ALLOWED_UPLOAD_FILES) 밖이거나 금지 모양인 경로를 올린다")

    def test_the_allow_list_is_one_constant_with_exactly_the_four_shapes(self):
        self.assertEqual(ALLOWED_UPLOAD_FILES, ("ChanceBlogDesktop-*-win64.zip", "SHA256SUMS", "PACKAGE_INFO.md", "PACKAGE_INFO.json"))
        source = Path(__file__).read_text(encoding="utf-8")
        self.assertEqual(len(re.findall(r"^ALLOWED_UPLOAD_\w+\s*=", source, re.M)), 1, "허용 목록은 이 모듈의 한 상수뿐이다(두 곳이 되면 어긋난다)")

    def test_the_decision_record_names_every_allowed_shape_and_the_rule_for_changing_the_list(self):
        """목록(상수)과 결정(D-344)은 같이 고친다 — 한쪽만 고치면 이 시험이 빨개진다."""
        row = next((line for line in (ROOT / "docs" / "DECISIONS.md").read_text(encoding="utf-8").splitlines() if line.startswith("| D-344 |")), "")
        self.assertTrue(row, "결정 D-344 행을 찾을 수 없다")
        for shape in ALLOWED_UPLOAD_FILES:
            self.assertIn(shape, row, f"결정 D-344 에 허용 목록의 {shape} 가 적혀 있어야 한다 — 새 업로드를 더하려면 이 목록과 결정을 같이 고친다")
        self.assertIn(CHANGE_RULE_SENTENCE, row)

    def test_the_workflows_in_main_today_upload_nothing_as_information_only(self):
        """정보 점검(오늘의 사실): `ci.yml`·`auto-pr.yml` 은 산출물을 올리지 않는다. **이 점검은 빨개지지 않는다** — 릴리스 패키지 워크플로처럼 허용 목록의 파일만 올리는 업로드는 정상이고,
        허용 밖의 업로드는 위의 규칙 시험이 따로 빨갛게 한다. 올리고 있으면 표준 오류에 알림 한 줄씩만 남긴다."""
        notes = main_upload_notes(workflow_texts())
        for note in notes:
            sys.stderr.write("정보: " + note + " — 허용 목록의 파일이면 정상이다(규칙 시험이 따로 본다)\n")
        self.assertIsInstance(notes, list)

    def test_the_steps_of_the_real_workflows_are_read(self):
        ci = steps_of(workflow_texts()["ci.yml"])
        self.assertEqual(len(ci), 3, "ci.yml 의 단계: 가져오기·파이썬·시험 실행")
        self.assertTrue(all(uses_of(step) for step in ci[:2]))
        auto = steps_of(workflow_texts()["auto-pr.yml"])
        self.assertEqual(len(auto), 1)

    def test_secrets_are_only_passed_through_env_and_never_printed(self):
        for name, text in workflow_texts().items():
            with self.subTest(workflow=name):
                self.assertEqual(secret_output_problems(text), [])

    def test_the_real_workflows_have_no_secrets_reference_in_a_run_body(self):
        for name, text in workflow_texts().items():
            for number, line in enumerate(text.splitlines(), start=1):
                if line.lstrip().startswith("#"):
                    continue
                self.assertNotRegex(line, r"echo[^\n]*\$\{\{\s*secrets\.", f"{name}:{number}")


class RuleSelfTest(unittest.TestCase):
    """규칙이 실제로 걸리는지 — 어기는 합성 워크플로는 빨개지고 올바른 합성 워크플로는 통과한다."""

    UPLOAD = """
jobs:
  build:
    steps:
      - uses: actions/checkout@aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
      - uses: actions/upload-artifact@bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
        with:
          name: out
          path: {path}
"""

    # PCKIT 초안(릴리스 패키지 미리보기)의 업로드 단계 그대로 — 허용 목록의 네 모양을 한 번에 올린다
    PACKAGE_UPLOAD = """
jobs:
  package:
    runs-on: windows-latest
    steps:
      - name: 올리기(압축 파일·SHA256SUMS·PACKAGE_INFO 만, 14일)
        uses: actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02  # v4.6.2
        with:
          name: ChanceBlogDesktop-preview
          path: |
            ${{ runner.temp }}/package/release/ChanceBlogDesktop-*-win64.zip
            ${{ runner.temp }}/package/release/SHA256SUMS
            ${{ runner.temp }}/package/release/PACKAGE_INFO.md
            ${{ runner.temp }}/package/release/PACKAGE_INFO.json
          retention-days: 14
          if-no-files-found: error
"""
    NO_UPLOAD = "jobs:\n  go:\n    steps:\n      - run: echo hi\n"

    def test_the_packaging_workflow_upload_with_its_four_files_passes(self):
        self.assertEqual(artifact_problems(self.PACKAGE_UPLOAD), [], "허용 목록의 네 모양만 올리는 단계는 통과한다")
        self.assertEqual(upload_inventory({"package.yml": self.PACKAGE_UPLOAD}),
                         {"package.yml": ["${{ runner.temp }}/package/release/" + shape for shape in ALLOWED_UPLOAD_FILES]})

    def test_each_allowed_file_passes_in_any_ordinary_folder_and_the_four_shapes_are_exact(self):
        for good in ("ChanceBlogDesktop-0.1.0-win64.zip", "ChanceBlogDesktop-*-win64.zip", "SHA256SUMS", "PACKAGE_INFO.md", "PACKAGE_INFO.json"):
            for folder in ("", "release/", "dist/", "${{ runner.temp }}/package/release/"):
                with self.subTest(path=folder + good):
                    self.assertEqual(artifact_problems(self.UPLOAD.format(path=folder + good)), [])

    def test_bad_uploads_are_caught(self):
        for bad in ("tests/logs/run.log", "data/", "build/out.log", "C:/Users/me/AppData/Local/ChanceblogDesktop", "dist/../secrets.env", "dist/test-results.log", ".env", "~/x",
                    "dist/ChanceBlogDesktop-setup.exe", "SHA256SUMS.txt", "PACKAGE_INFO.log", "PACKAGE_INFO", "release/*", "release/", "${{ runner.temp }}/**/SHA256SUMS",
                    "ChanceBlogDesktop-*.zip", "tests/ChanceBlogDesktop-0.1.0-win64.zip", "logs/SHA256SUMS", "data/PACKAGE_INFO.json", "release/test-results.json",
                    "release/ChanceBlogDesktop-0.1.0-win64.zip.log", "release/PACKAGE_INFO.json.bak"):
            with self.subTest(path=bad):
                self.assertTrue(artifact_problems(self.UPLOAD.format(path=bad)), "허용 목록 밖이거나 금지 모양이라 걸려야 한다")

    def test_a_multi_line_path_list_is_checked_line_by_line(self):
        text = self.UPLOAD.format(path="|\n            SHA256SUMS\n            tests/out.log\n            dist/app.exe")
        problems = artifact_problems(text)
        self.assertEqual([item[1] for item in problems], ["tests/out.log", "dist/app.exe"])

    def test_an_upload_without_a_path_is_caught_and_a_workflow_without_one_is_clean(self):
        self.assertTrue(artifact_problems("jobs:\n  b:\n    steps:\n      - uses: actions/upload-artifact@cccccccccccccccccccccccccccccccccccccccc\n        with:\n          name: x\n"))
        self.assertEqual(artifact_problems(self.NO_UPLOAD), [])
        self.assertEqual(upload_inventory({"x.yml": self.NO_UPLOAD}), {})

    def test_the_pages_artifact_action_is_read_as_an_upload_too(self):
        text = "jobs:\n  b:\n    steps:\n      - uses: actions/upload-pages-artifact@dddddddddddddddddddddddddddddddddddddddd\n        with:\n          path: _site/\n"
        self.assertEqual([item[1] for item in artifact_problems(text)], ["_site/"])

    def test_the_main_workflow_note_is_information_only_an_allowed_upload_is_a_note_never_a_failure(self):
        quiet = {"ci.yml": self.NO_UPLOAD, "auto-pr.yml": self.NO_UPLOAD}
        self.assertEqual(main_upload_notes(quiet), [], "오늘의 사실 — main 의 두 워크플로는 업로드가 없다")
        allowed = {"ci.yml": self.PACKAGE_UPLOAD, "auto-pr.yml": self.NO_UPLOAD}
        notes = main_upload_notes(allowed)
        self.assertEqual(len(notes), 1)
        self.assertIn("ci.yml", notes[0])
        self.assertEqual(artifact_problems(allowed["ci.yml"]), [], "허용된 업로드라 규칙은 통과한다 — 빨개지는 쪽은 없다")
        self.assertEqual(main_upload_notes({"package.yml": self.PACKAGE_UPLOAD}), [], "새 워크플로 파일의 업로드는 알림 대상도 아니다")
        refused = self.UPLOAD.format(path="tests/out.log")
        self.assertTrue(artifact_problems(refused), "허용 밖의 업로드는 어느 워크플로에서든 규칙이 빨갛게 한다")

    WORKFLOW = """
jobs:
  go:
    runs-on: ubuntu-latest
    steps:
      - name: step
        env:
          TOKEN_VALUE: ${{{{ secrets.MY_SECRET }}}}
        run: |
          {body}
"""

    def test_printing_a_secret_env_or_the_whole_environment_is_caught(self):
        for body in ('echo "$TOKEN_VALUE"', 'printf "%s" "${TOKEN_VALUE}"', 'cat <<< "$TOKEN_VALUE"', "set -x", "env", "printenv", "export -p", "set -euxo pipefail", 'echo "x"; env'):
            with self.subTest(body=body):
                text = self.WORKFLOW.format(body=body)
                self.assertTrue(secret_output_problems(text), f"{body}: 걸려야 한다")

    ONE_LINE = """
jobs:
  go:
    runs-on: ubuntu-latest
    steps:
      - name: step
        env:
          TOK: ${{{{ secrets.MY_SECRET }}}}
        run: {command}
"""

    def test_a_one_line_run_is_read_as_a_command_too(self):
        """PCSEC1V D2: `run: |` 블록만 읽어 `env:` 로 받은 비밀을 한 줄 `run:` 으로 찍는 것을 놓쳤다."""
        for command in ('echo "$TOK"', "printenv", "env | sort", "printf '%s' \"$TOK\" > f && cat f", "echo ${TOK}", 'cat <<< "$TOK"', 'tee out.txt <<< "$TOK"', "set -x", '"echo $TOK"', "'printenv'"):
            with self.subTest(command=command):
                self.assertTrue(secret_output_problems(self.ONE_LINE.format(command=command)), f"{command}: 한 줄 run 이어도 걸려야 한다")

    def test_innocent_one_line_runs_are_not_caught(self):
        for command in ("python scripts/ci_shard.py", 'test -n "$TOK" && echo "설정됨"', 'echo "길이 ${#TOK}"', "echo hello", "python -m unittest discover -s tests", "'python -m unittest'"):
            with self.subTest(command=command):
                self.assertEqual(secret_output_problems(self.ONE_LINE.format(command=command)), [], f"{command}: 통과해야 한다")

    def test_a_secret_inside_a_run_body_is_caught_but_env_passing_and_innocent_commands_are_not(self):
        inside = "jobs:\n  go:\n    steps:\n      - run: echo ${{ secrets.MY_SECRET }}\n"
        self.assertTrue(secret_output_problems(inside))
        good = self.WORKFLOW.format(body='gh api "repos/x/y" --silent; test -n "$TOKEN_VALUE" && echo "토큰이 설정돼 있다"; echo "길이 ${#TOKEN_VALUE}"')
        self.assertEqual(secret_output_problems(good), [], "env 로 받고 값을 내지 않는 모양은 통과한다")
        self.assertEqual(secret_output_problems(self.WORKFLOW.format(body="python scripts/ci_shard.py")), [])


if __name__ == "__main__":
    unittest.main()
