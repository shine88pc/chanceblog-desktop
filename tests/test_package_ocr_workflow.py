"""추가 도구(글자 읽기) 빌드 워크플로 초안(`.github/workflows/package-ocr.yml` — T3, 운영자 승인 범위: 수동 실행·읽기 권한·비밀 0·액션 SHA 고정, 병합은 운영자만)의 규칙 시험(결정 D-530).

글만 읽는다(네트워크·GitHub 없이, PyYAML 없이 — 앱 CI 네 칸에서 같은 방식으로 돈다). 본체 `package.yml` 의 시험(`test_packaging_workflow.py`)과 같은 모양이다. 지키는 것:
  트리거는 `workflow_dispatch` 하나이고 입력칸이 없다 · `permissions` 는 최상위 `contents: read` 하나(작업 단위로 넓히지 못한다) · `secrets.`·토큰 0 · 모든 `uses:` 가 40자리 SHA 이고 `package.yml` 이 쓰는 것과
  같은 것뿐(새 액션 0) · `pull_request_target` 없음 · `run:` 안에 `${{ … }}`(`github.event`·입력 포함)가 하나도 없음 · `run:` 한 단계에 명령 하나(PowerShell 은 마지막 명령의 종료 코드만 본다) ·
  모든 설치는 `--require-hashes` · 모델은 `fetch_models.py`·빌드는 `build_ocr_addon.py all … --require-clean`(점검 끄는 옵션 없음) · 올리는 것은 압축 파일·SHA256SUMS·PACKAGE_INFO.json 뿐(이름·보존 14일·없으면 실패).
그 위에 **글을 구조로 읽는 허용 목록 규칙**(`tests/workflow_yaml_support.py` 의 작은 읽개 — 흐름식·앵커·겹친 키 같은 다른 표기는 읽을 수 없다고 거절): 최상위·작업·단계 키와 액션별 `with` 키, 작업 `env`, 열한 단계의 명령이 정해진 글과 같다
(독립 검증 S 의 SP-2·Q 의 QP-3 — 금지 낱말 찾기만으로는 한 줄 흐름식 단계·키 끼워 넣기·pip 색인 환경 변수 같은 우회를 못 막았다). 이 규칙 검사 자체도 좋은 글·나쁜 글로 시험한다. 이 워크플로가 GitHub 러너에서 실제로 도는지는 여기서 확인할 수 없다(병합 뒤 운영자가 수동 실행).
"""
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ocr_build_support as support  # noqa: E402
import test_workflow_artifacts as wf  # noqa: E402  (단계·`uses:`·업로드 경로를 읽는 같은 도우미)
import workflow_yaml_support as yamlsub  # noqa: E402  (글을 구조로 읽는 작은 읽개 — 표준 라이브러리만)

ROOT = support.ROOT
WORKFLOW = ROOT / ".github" / "workflows" / "package-ocr.yml"
REFERENCE = ROOT / ".github" / "workflows" / "package.yml"
ARTIFACT_NAME = "ChanceBlogDesktop-OCR-preview"
UPLOAD_PATHS = ("ocr/release/ChanceBlogDesktop-OCR-*-win64.zip", "ocr/release/SHA256SUMS", "ocr/release/PACKAGE_INFO.json")
ACTION_NAMES = {"actions/checkout", "actions/setup-python", "actions/upload-artifact"}
NETWORK_TOOLS = ("curl", "wget", "Invoke-WebRequest", "Invoke-RestMethod", "iwr ", "irm ", "Start-BitsTransfer", "git clone", "git fetch", "git pull", "npm ", "choco ", "winget ")
SHA_REF = re.compile(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}")


def code_of(text):
    """주석 줄을 뺀 글 — 주석 안의 `secrets.` 나 `write` 낱말은 센 것이 아니다."""
    return "\n".join(line for line in text.replace("\r\n", "\n").split("\n") if not line.lstrip().startswith("#"))


def top_block(code, key):
    """최상위 `key:` 아래의 들여쓴 줄들(없으면 None) — 같은 줄에 적은 값은 맨 앞 항목으로."""
    block, inside = [], False
    for line in code.split("\n"):
        if not inside:
            match = re.match(rf"^{key}:(.*)$", line)
            if match:
                inside = True
                if match.group(1).strip():
                    block.append(match.group(1).strip())
            continue
        if line and not line.startswith((" ", "\t")):
            break
        block.append(line)
    return block if inside else None


def run_bodies(text):
    """모든 `run:` 의 명령 글(한 줄 값이거나 `|` 블록) — 단계 순서대로."""
    return [wf.block_after(step, "run") for step in wf.steps_of(text) if re.search(r"^\s*-?\s*run:|^\s+run:", step, re.M)]


def uses_refs(text):
    return re.findall(r"\buses:\s*([^\s,}#]+)", code_of(text))                       # 한 줄 흐름식 `- {uses: …}` 안의 것도 찾는다(독립 검증 S 의 SP-2)


JOB_NAME = "package-ocr"
TOP_KEYS = {"name", "on", "permissions", "concurrency", "jobs"}
JOB_KEYS = {"name", "runs-on", "timeout-minutes", "env", "steps"}
STEP_KEYS = {"name", "uses", "with", "run"}
CONCURRENCY = {"group": "package-ocr-${{ github.ref }}", "cancel-in-progress": "false"}
VENV_PYTHON = '"$env:RUNNER_TEMP/ocr-venv/Scripts/python.exe"'
# 이 흐름의 열한 단계 — 허용 목록이다. 단계를 더하거나 빼거나 명령·with 를 바꾸려면 이 목록(과 시험)을 같이 고쳐야 하므로 운영자 눈에 띈다(독립 검증 S 의 SP-2·Q 의 QP-3).
EXPECTED_STEPS = (
    ("uses", "actions/checkout", {"persist-credentials": "false"}),
    ("uses", "actions/setup-python", {"python-version": "3.12"}),
    ("run", 'python -m venv "$env:RUNNER_TEMP/ocr-venv"'),
    ("run", "& " + VENV_PYTHON + " -m pip install --require-hashes --only-binary=:all: -r ocr_addon/requirements-ocr.lock"),
    ("run", "& " + VENV_PYTHON + " -m pip install --require-hashes --only-binary=:all: -r ocr_addon/requirements-build.txt"),
    ("run", "& " + VENV_PYTHON + " -m pip check"),
    ("run", 'python ocr_addon/fetch_models.py --dest "$env:RUNNER_TEMP/ocr_models"'),
    ("run", "& " + VENV_PYTHON + ' ocr_addon/build_ocr_addon.py all --out-dir "$env:RUNNER_TEMP/ocr" --models-dir "$env:RUNNER_TEMP/ocr_models" --require-clean'),
    ("run", 'python ocr_addon/verify_release.py --release "$env:RUNNER_TEMP/ocr/release"'),
    ("run", 'Get-Content "$env:RUNNER_TEMP/ocr/release/SHA256SUMS"'),
    ("uses", "actions/upload-artifact", {"name": ARTIFACT_NAME, "path": "".join("${{ runner.temp }}/" + path + "\n" for path in UPLOAD_PATHS), "retention-days": "14", "if-no-files-found": "error"}),
)


def one_command(line):
    """한 줄 명령이 명령 하나인가 — 따옴표 안을 지우고 맨 앞의 호출 연산자(& )만 빼고 나서 `;`·`&`·`|`·백틱·`$(` 가 없다(PowerShell 7 의 단일 &·파이프·하위 식도 명령 둘로 센다)."""
    plain = re.sub(r"'[^']*'", "''", re.sub(r'"[^"]*"', '""', line))
    plain = re.sub(r"^\s*&\s+", "", plain)
    return not re.search(r"[;&|`]|\$\(", plain)


def step_problems(position, step, expected, reference_refs):
    if not isinstance(step, dict):
        return [f"구조: 단계 키 — 단계 {position} 가 매핑이 아니다"]
    problems = []
    extra = sorted(set(step) - STEP_KEYS)
    if extra:
        problems.append(f"구조: 단계 키 — 단계 {position} 에 허용되지 않은 키가 있다(env·shell·if·working-directory 같은 키를 못 끼운다): {extra}")
    if "name" in step and not (isinstance(step["name"], str) and step["name"].strip()):
        problems.append(f"구조: 단계 키 — 단계 {position} 의 name 이 비어 있다")
    if expected[0] == "uses":
        _kind, action, with_ = expected
        ref = step.get("uses")
        if "run" in step or not isinstance(ref, str):
            problems.append(f"구조: 단계 목록 — 단계 {position} 는 uses({action}) 단계여야 한다")
            return problems
        if ref.split("@")[0] != action or ref not in reference_refs:
            problems.append(f"구조: 액션 — 단계 {position} 의 액션이 정해진 것({action})이 아니거나 package.yml 과 같은 SHA 가 아니다: {ref}")
        if step.get("with") != with_:
            problems.append(f"구조: with — 단계 {position} 의 with 가 정해진 것과 다르다(키 하나도 더하거나 바꾸지 못한다): {step.get('with')!r}")
    else:
        _kind, command = expected
        if "uses" in step or "with" in step or step.get("run") != command:
            problems.append(f"구조: run — 단계 {position} 의 run 명령이 정해진 글과 다르다: {str(step.get('run'))[:80]!r}")
    return problems


def structure_problems(text, reference_refs):
    """글을 '구조'로 읽어(흐름식·앵커·겹친 키 같은 표기는 읽을 수 없다고 거절) 승인 조건을 허용 목록으로 견준다 — 금지 낱말 찾기가 놓치는 우회 표기를 막는다(독립 검증 S 의 SP-2·Q 의 QP-3)."""
    try:
        tree = yamlsub.load(text)
    except yamlsub.YamlSubsetError as error:
        return [f"구조: 읽을 수 없는 표기 — {error}"]
    if not isinstance(tree, dict) or set(tree) != TOP_KEYS:
        return [f"구조: 최상위 키 — 정해진 다섯({sorted(TOP_KEYS)})과 다르다: {sorted(tree) if isinstance(tree, dict) else type(tree).__name__}"]
    problems = []
    if tree["on"] != {"workflow_dispatch": None}:
        problems.append(f"구조: on — workflow_dispatch 하나(입력칸 없음)여야 한다: {tree['on']!r}")
    if tree["permissions"] != {"contents": "read"}:
        problems.append(f"구조: permissions — contents: read 하나여야 한다: {tree['permissions']!r}")
    if tree["concurrency"] != CONCURRENCY:
        problems.append(f"구조: concurrency — 정해진 값이 아니다: {tree['concurrency']!r}")
    jobs = tree["jobs"]
    if not isinstance(jobs, dict) or list(jobs) != [JOB_NAME]:
        return problems + [f"구조: 작업 — {JOB_NAME} 하나여야 한다"]
    job = jobs[JOB_NAME]
    if not isinstance(job, dict) or set(job) != JOB_KEYS:
        return problems + [f"구조: 작업 키 — 정해진 다섯({sorted(JOB_KEYS)})과 다르다(environment·container·services·defaults·permissions 같은 키를 못 끼운다): {sorted(job) if isinstance(job, dict) else type(job).__name__}"]
    if job["runs-on"] != "windows-latest" or not re.fullmatch(r"[1-9]|[1-3][0-9]|4[0-5]", str(job["timeout-minutes"])):
        problems.append("구조: 작업 값 — runs-on 은 windows-latest, timeout-minutes 는 1에서 45 여야 한다")
    if job["env"] != {"PYTHONUTF8": "1"}:
        problems.append(f"구조: 작업 env — PYTHONUTF8 하나여야 한다(PIP_INDEX_URL·프록시·인증서·경로 환경 변수를 못 끼운다): {job['env']!r}")
    steps = job["steps"]
    if not isinstance(steps, list) or len(steps) != len(EXPECTED_STEPS):
        problems.append(f"구조: 단계 목록 — 정해진 {len(EXPECTED_STEPS)} 단계와 다르다({len(steps) if isinstance(steps, list) else type(steps).__name__}) — 단계를 더하거나 빼려면 이 시험의 정해진 목록도 같이 고친다")
    else:
        for position, (step, expected) in enumerate(zip(steps, EXPECTED_STEPS), 1):
            problems += step_problems(position, step, expected, reference_refs)
    return problems


def violations(text, reference_refs):
    """워크플로 글이 어긴 규칙의 목록(없으면 빈 목록). reference_refs: package.yml 이 쓰는 `액션@SHA` 들."""
    code = code_of(text)
    problems = []
    triggers = []
    for line in top_block(code, "on") or []:
        match = re.match(r"^  ([a-z_]+):", line)
        if match:
            triggers.append(match.group(1))
        elif line.strip() and not line.startswith(" "):
            triggers += re.findall(r"[a-z_]+", line)
    if sorted(set(triggers)) != ["workflow_dispatch"]:
        problems.append(f"on: 은 workflow_dispatch 하나여야 한다({sorted(set(triggers))})")
    if re.search(r"(?m)^\s+inputs:", "\n".join(top_block(code, "on") or [])):
        problems.append("workflow_dispatch 에 입력칸(inputs)이 있다 — 이 흐름은 입력을 받지 않는다")
    permissions = [line.strip() for line in (top_block(code, "permissions") or []) if line.strip()]
    if permissions != ["contents: read"]:
        problems.append(f"최상위 permissions 는 contents: read 하나여야 한다({permissions})")
    if len(re.findall(r"(?m)^\s*permissions:", code)) != 1:
        problems.append("permissions 가 최상위 하나가 아니다(작업 단위로 넓힐 수 없다)")
    if re.search(r"\bwrite(-all)?\b", code):
        problems.append("쓰기 권한 낱말(write)이 있다")
    for word in ("secrets.", "secrets:", "github.token", "GITHUB_TOKEN", "id-token"):
        if word in code:
            problems.append(f"비밀·토큰을 쓴다: {word}")
    for pattern, label in ((r"\bsecrets\b", "secrets 낱말"), (r"github\s*\[", "github[…] 꼴 참조"), (r"\btoJSON\s*\(", "toJSON(…) 로 맥락 통째 꺼내기")):
        if re.search(pattern, code):
            problems.append(f"비밀·토큰을 쓴다: {label}")
    for word in ("pull_request_target", "pull_request", "schedule:", "workflow_run", "repository_dispatch"):
        if word in code:
            problems.append(f"허용되지 않는 트리거 낱말: {word}")
    if re.findall(r"runs-on:\s*(\S+)", code) != ["windows-latest"]:
        problems.append("runs-on 은 windows-latest 하나여야 한다")
    if not re.search(r"python-version:\s*['\"]?3\.12['\"]?\s*$", code, re.M):
        problems.append("파이썬 3.12 를 쓴다")
    if not re.search(r"^\s*timeout-minutes:\s*(?:[1-9]|[1-3][0-9]|4[0-5])\s*$", code, re.M):
        problems.append("timeout-minutes 가 1에서 45 사이가 아니다")
    refs = uses_refs(text)
    for ref in refs:
        if not SHA_REF.fullmatch(ref):
            problems.append(f"액션이 전체 커밋 SHA 로 고정되지 않았다: {ref}")
        elif ref not in reference_refs:
            problems.append(f"package.yml 이 쓰지 않는 액션·SHA 다(새 액션·다른 SHA): {ref}")
    if {ref.split("@")[0] for ref in refs} != ACTION_NAMES:
        problems.append(f"쓰는 액션이 {sorted(ACTION_NAMES)} 셋이 아니다")
    if not re.search(r"persist-credentials:\s*false", code):
        problems.append("checkout 이 persist-credentials: false 가 아니다")
    bodies = run_bodies(text)
    for body in bodies:
        if "${{" in body:
            problems.append(f"run: 안에 ${{{{ }}}} 가 있다(주입 길): {body.strip()[:60]}")
        lines = [line for line in body.splitlines() if line.strip()]
        if len(lines) != 1 or not one_command(lines[0]):
            problems.append(f"run: 한 단계에 명령이 하나가 아니다: {body.strip()[:60]}")
        for tool in NETWORK_TOOLS:
            if tool in body:
                problems.append(f"run: 에서 새 외부 접속 도구를 쓴다: {tool.strip()}")
        if re.search(r"pip(?:3)?(?:\.exe)?\"?\s+install", body) or " -m pip install" in body:
            if "--require-hashes" not in body or "--only-binary=:all:" not in body or not re.search(r"-r\s+ocr_addon/requirements-[a-z-]+\.(?:lock|txt)", body):
                problems.append(f"pip 설치가 --require-hashes --only-binary=:all: -r 잠금 파일 꼴이 아니다: {body.strip()[:60]}")
    joined = "\n".join(bodies)
    if joined.count("-m pip install") != 2 or not re.search(r"requirements-ocr\.lock", joined) or not re.search(r"requirements-build\.txt", joined):
        problems.append("설치는 잠금 파일 둘(requirements-ocr.lock·requirements-build.txt)을 각각 한 번씩이어야 한다")
    if "ocr_addon/fetch_models.py --dest" not in joined:
        problems.append("모델 받기(ocr_addon/fetch_models.py)를 실행하지 않는다")
    build = [body for body in bodies if "ocr_addon/build_ocr_addon.py" in body]
    if len(build) != 1 or " all " not in build[0] or "--require-clean" not in build[0] or "--models-dir" not in build[0]:
        problems.append("빌드는 `build_ocr_addon.py all --models-dir … --require-clean` 한 단계여야 한다")
    for word in ("--no-selftest", "--no-remove", "--skip", "--allow", "--variant", "--extra-exclude", "--lock", "--no-notices", "--no-licenses", "--no-verify"):
        if word in joined:
            problems.append(f"점검·제거를 끄는 옵션 낱말: {word}")
    if re.search(r"(?m)^\s+(?:-\s+)?(?:if|continue-on-error):", code):
        problems.append("단계에 if·continue-on-error 가 있다 — 실패한 단계를 건너뛰어 초록으로 끝나는 길이 된다")
    steps = wf.steps_of(text)
    run_of = [wf.block_after(step, "run") for step in steps]
    build_at = [index for index, body in enumerate(run_of) if "ocr_addon/build_ocr_addon.py" in body]
    verify_at = [index for index, body in enumerate(run_of) if "ocr_addon/verify_release.py" in body]
    upload_at = [index for index, step in enumerate(steps) if wf.UPLOAD_ACTION.search(wf.uses_of(step))]
    if len(verify_at) != 1 or not re.search(r'verify_release\.py --release "\$env:RUNNER_TEMP/ocr/release"\s*$', run_of[verify_at[0]].strip()):
        problems.append('산출물 점검은 `python ocr_addon/verify_release.py --release "$env:RUNNER_TEMP/ocr/release"` 한 단계여야 한다')
    elif not (build_at and upload_at and build_at[0] < verify_at[0] < upload_at[0]):
        problems.append("산출물 점검 단계는 빌드 단계 뒤·올리기 단계 앞에 있어야 한다")
    uploads = wf.upload_steps(text)
    if len(uploads) != 1:
        problems.append(f"upload-artifact 가 정확히 한 번이어야 한다({len(uploads)})")
    for _number, step in uploads:
        if not re.search(rf"^\s*name:\s*{re.escape(ARTIFACT_NAME)}\s*$", step, re.M):
            problems.append(f"올리는 산출물 이름은 {ARTIFACT_NAME} 이어야 한다")
        entries = [item.replace("${{ runner.temp }}/", "") for item in wf.upload_paths(step)]
        if entries != list(UPLOAD_PATHS):
            problems.append(f"올리는 경로가 정해진 셋이 아니다: {entries}")
        if not re.search(r"^\s*retention-days:\s*14\s*$", step, re.M):
            problems.append("retention-days: 14 가 아니다")
        if not re.search(r"^\s*if-no-files-found:\s*error\s*$", step, re.M):
            problems.append("if-no-files-found: error 가 아니다")
    if wf.artifact_problems(text):
        problems.append(f"본체의 산출물 허용 목록 규칙에 걸린다: {wf.artifact_problems(text)}")
    if wf.secret_output_problems(text):
        problems.append(f"비밀 출력 규칙에 걸린다: {wf.secret_output_problems(text)}")
    problems += structure_problems(text, reference_refs)
    return problems


REAL = WORKFLOW.read_text(encoding="utf-8").replace("\r\n", "\n") if WORKFLOW.exists() else ""
REFS = set(uses_refs(REFERENCE.read_text(encoding="utf-8"))) if REFERENCE.exists() else set()


def mutate(old, new, count=1):
    assert REAL.count(old) == count, (old, REAL.count(old))
    return REAL.replace(old, new)


class RealWorkflowTest(unittest.TestCase):
    def test_the_files_exist_and_the_reference_workflow_pins_three_actions(self):
        self.assertTrue(WORKFLOW.is_file(), "package-ocr.yml 이 있어야 한다(NO-MERGE 가지의 초안)")
        self.assertTrue(REFERENCE.is_file(), "기준 package.yml 이 있어야 한다 — 없으면 새 액션 0 을 견줄 수 없다")
        self.assertEqual({ref.split("@")[0] for ref in REFS}, ACTION_NAMES)
        self.assertEqual(len(REFS), 3)

    def test_the_workflow_follows_every_rule(self):
        self.assertEqual(violations(REAL, REFS), [])

    def test_every_action_is_the_very_same_pinned_reference_package_yml_uses(self):
        refs = uses_refs(REAL)
        self.assertEqual(sorted(refs), sorted(REFS))
        for ref in refs:
            self.assertRegex(ref, r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$")            # test_repo_layout 의 SHA 고정 시험과 같은 모양

    def test_the_other_existing_guards_accept_it_too(self):
        self.assertEqual(wf.artifact_problems(REAL), [])
        self.assertEqual(wf.secret_output_problems(REAL), [])
        self.assertEqual(wf.main_upload_notes({"package-ocr.yml": REAL}), [], "새 워크플로 파일의 업로드는 알림 대상이 아니다")
        self.assertIn("package-ocr.yml", wf.workflow_texts())

    def test_there_is_exactly_one_upload_and_its_three_files_fit_the_allowed_shapes(self):
        uploads = wf.upload_steps(REAL)
        self.assertEqual(len(uploads), 1)
        paths = wf.upload_paths(uploads[0][1])
        self.assertEqual(len(paths), 3)
        for path in paths:
            self.assertEqual(wf.path_problem(path), "", path)

    def test_the_build_runs_the_two_scripts_that_exist_with_the_flags_they_have(self):
        joined = "\n".join(run_bodies(REAL))
        for script in ("ocr_addon/fetch_models.py", "ocr_addon/build_ocr_addon.py"):
            self.assertIn(script, joined)
            self.assertTrue((ROOT / script).is_file(), script)
        build_source = support.read("ocr_addon/build_ocr_addon.py")
        for flag in ("--out-dir", "--models-dir", "--require-clean"):
            self.assertIn(flag, build_source, f"워크플로가 쓰는 {flag} 를 빌드 스크립트가 받는다")
        self.assertIn("--dest", support.read("ocr_addon/fetch_models.py"))
        self.assertTrue((ROOT / "ocr_addon" / "verify_release.py").is_file(), "산출물 점검 스크립트")
        self.assertIn("--release", support.read("ocr_addon/verify_release.py"))
        for lock in ("ocr_addon/requirements-ocr.lock", "ocr_addon/requirements-build.txt"):
            self.assertTrue((ROOT / lock).is_file(), lock)

    def test_the_workflow_text_has_no_tilde_and_no_web_address(self):
        text = REAL
        self.assertTrue(text.strip(), "워크플로 글이 비어 있다 — 파일이 없으면 이 시험은 통과하면 안 된다")
        self.assertNotIn(chr(0x7E), text)
        self.assertIsNone(re.search(r"(?i)https?://|www[.]", text))


VERIFY_RUN = 'run: python ocr_addon/verify_release.py --release "$env:RUNNER_TEMP/ocr/release"'
VERIFY_BLOCK = "      - name: 산출물 점검(압축 파일의 해시·크기·파일 목록과 라이선스 고지 파일이 들어 있는지)\n        " + VERIFY_RUN + "\n\n"


def bad_variants():
    """규칙을 하나씩 어기는 나쁜 글 — 진짜 파일(REAL)을 한 군데씩 바꾼 것이다(바꿀 글이 정확히 한 번 나오지 않으면 `mutate` 가 멈춘다)."""
    return {
        "push trigger": mutate("on:\n  workflow_dispatch:\n", "on:\n  workflow_dispatch:\n  push:\n"),
        "pull_request trigger": mutate("on:\n  workflow_dispatch:\n", "on:\n  workflow_dispatch:\n  pull_request:\n"),
        "pull_request_target": mutate("on:\n  workflow_dispatch:\n", "on:\n  workflow_dispatch:\n  pull_request_target:\n"),
        "schedule trigger": mutate("on:\n  workflow_dispatch:\n", "on:\n  workflow_dispatch:\n  schedule:\n    - cron: '0 0 * * *'\n"),
        "workflow_run trigger": mutate("on:\n  workflow_dispatch:\n", "on:\n  workflow_run:\n    workflows: ['x']\n"),
        "no trigger": mutate("on:\n  workflow_dispatch:\n", ""),
        "inline on list": mutate("on:\n  workflow_dispatch:\n", "on: [push, workflow_dispatch]\n"),
        "dispatch input": mutate("on:\n  workflow_dispatch:\n", "on:\n  workflow_dispatch:\n    inputs:\n      tag:\n        required: false\n"),
        "write permission": mutate("permissions:\n  contents: read\n", "permissions:\n  contents: write\n"),
        "extra permission": mutate("  contents: read\n", "  contents: read\n  id-token: write\n"),
        "no permissions": mutate("permissions:\n  contents: read\n", ""),
        "read-all": mutate("permissions:\n  contents: read\n", "permissions: read-all\n"),
        "job permissions": mutate("    timeout-minutes: 45\n", "    timeout-minutes: 45\n    permissions:\n      contents: read\n"),
        "ubuntu runner": mutate("windows-latest", "ubuntu-latest"),
        "python 3.11": mutate("'3.12'", "'3.11'"),
        "no timeout": mutate("    timeout-minutes: 45\n", ""),
        "huge timeout": mutate("timeout-minutes: 45", "timeout-minutes: 360"),
        "unpinned checkout": mutate("actions/checkout@11d5960a326750d5838078e36cf38b85af677262", "actions/checkout@v4"),
        "short sha": mutate("actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065", "actions/setup-python@a26af69"),
        "other sha": mutate("actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02", "actions/upload-artifact@" + "0" * 40),
        "new action": mutate("      - uses: actions/setup-python@", "      - uses: actions/cache@" + "1" * 40 + "\n      - uses: actions/setup-python@"),
        "third party action": mutate("      - uses: actions/setup-python@", "      - uses: someone/tool@" + "2" * 40 + "\n      - uses: actions/setup-python@"),
        "credentials kept": mutate("persist-credentials: false", "persist-credentials: true"),
        "secret value": mutate("      - name: SHA-256 보기", "      - env:\n          K: ${{ secrets.KEY }}\n        name: SHA-256 보기"),
        "github token": mutate("persist-credentials: false", "persist-credentials: false\n          token: ${{ github.token }}"),
        "github.event in run": mutate('run: Get-Content "$env:RUNNER_TEMP/ocr/release/SHA256SUMS"', 'run: echo ${{ github.event.head_commit.message }}'),
        "inputs in run": mutate('run: Get-Content "$env:RUNNER_TEMP/ocr/release/SHA256SUMS"', 'run: Write-Output ${{ inputs.tag }}'),
        "context in build run": mutate('--out-dir "$env:RUNNER_TEMP/ocr" --models', '--out-dir "${{ runner.temp }}/ocr" --models'),
        "two commands in one step": mutate('run: python -m venv "$env:RUNNER_TEMP/ocr-venv"', 'run: python -m venv "$env:RUNNER_TEMP/ocr-venv"; python --version'),
        "and-and in one step": mutate('run: Get-Content "$env:RUNNER_TEMP/ocr/release/SHA256SUMS"', 'run: Get-Content "$env:RUNNER_TEMP/ocr/release/SHA256SUMS" && echo done'),
        "multi line run": mutate('run: python ocr_addon/fetch_models.py --dest "$env:RUNNER_TEMP/ocr_models"', 'run: |\n          python ocr_addon/fetch_models.py --dest "$env:RUNNER_TEMP/ocr_models"\n          python --version'),
        "no require-hashes (lock)": mutate("pip install --require-hashes --only-binary=:all: -r ocr_addon/requirements-ocr.lock", "pip install --only-binary=:all: -r ocr_addon/requirements-ocr.lock"),
        "no require-hashes (build)": mutate("pip install --require-hashes --only-binary=:all: -r ocr_addon/requirements-build.txt", "pip install --only-binary=:all: -r ocr_addon/requirements-build.txt"),
        "no only-binary": mutate("--require-hashes --only-binary=:all: -r ocr_addon/requirements-ocr.lock", "--require-hashes -r ocr_addon/requirements-ocr.lock"),
        "unpinned install": mutate('pip install --require-hashes --only-binary=:all: -r ocr_addon/requirements-build.txt', 'pip install pyinstaller'),
        "extra pip step": mutate("      - name: 설치된 패키지끼리 맞는지 확인", '      - run: \'& "$env:RUNNER_TEMP/ocr-venv/Scripts/python.exe" -m pip install pefile\'\n      - name: 설치된 패키지끼리 맞는지 확인'),
        "curl download": mutate("      - name: 설치된 패키지끼리 맞는지 확인", "      - run: curl -O https://example.invalid/x.zip\n      - name: 설치된 패키지끼리 맞는지 확인"),
        "web request": mutate("      - name: 설치된 패키지끼리 맞는지 확인", "      - run: Invoke-WebRequest -Uri https://example.invalid/x -OutFile x\n      - name: 설치된 패키지끼리 맞는지 확인"),
        "no fetch step": mutate('python ocr_addon/fetch_models.py --dest "$env:RUNNER_TEMP/ocr_models"', "python --version"),
        "no require-clean": mutate(' --require-clean', ''),
        "no models-dir": mutate(' --models-dir "$env:RUNNER_TEMP/ocr_models"', ''),
        "selftest off": mutate(' --require-clean', ' --require-clean --no-selftest'),
        "removal off": mutate(' --require-clean', ' --require-clean --no-remove'),
        "stage not all": mutate("build_ocr_addon.py all ", "build_ocr_addon.py freeze "),
        "artifact name": mutate("name: ChanceBlogDesktop-OCR-preview", "name: something-else"),
        "extra upload path": mutate("ocr/release/PACKAGE_INFO.json\n", "ocr/release/PACKAGE_INFO.json\n            ${{ runner.temp }}/ocr/build.log\n"),
        "work folder upload": mutate("${{ runner.temp }}/ocr/release/SHA256SUMS", "${{ runner.temp }}/ocr/dist/SHA256SUMS"),
        "wildcard upload": mutate("ChanceBlogDesktop-OCR-*-win64.zip", "*"),
        "info under old name": mutate("ocr/release/PACKAGE_INFO.json", "ocr/release/OCR_INFO.json"),
        "retention 30": mutate("retention-days: 14", "retention-days: 30"),
        "no retention": mutate("          retention-days: 14\n", ""),
        "no error on empty": mutate("if-no-files-found: error", "if-no-files-found: warn"),
        "no upload": REAL[:REAL.index("      - name: 올리기")],
        "no verify step": mutate(VERIFY_BLOCK, ""),
        "verify replaced": mutate(VERIFY_RUN, "run: python --version"),
        "verify before build": mutate(VERIFY_BLOCK, "").replace("      - name: 추가 도구 만들기(", VERIFY_BLOCK + "      - name: 추가 도구 만들기(", 1),
        "verify after upload": mutate(VERIFY_BLOCK, "") + VERIFY_BLOCK,
        "verify without release": mutate(' --release "$env:RUNNER_TEMP/ocr/release"', ""),
        "continue on error": mutate(VERIFY_BLOCK, VERIFY_BLOCK.replace("      - name:", "      - continue-on-error: true\n        name:", 1)),
        "step condition": mutate(VERIFY_BLOCK, VERIFY_BLOCK.replace("      - name:", "      - if: false\n        name:", 1)),
        "verify with lock": mutate(' --release "$env:RUNNER_TEMP/ocr/release"', ' --release "$env:RUNNER_TEMP/ocr/release" --lock x.json'),
        "two uploads": REAL + "\n      - uses: actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02  # v4.6.2\n        with:\n          name: x\n          path: ${{ runner.temp }}/ocr/release/SHA256SUMS\n          retention-days: 14\n          if-no-files-found: error\n",
    }


# 변형 -> 그 변형 때문에 울려야 하는 규칙의 낱말(다른 규칙이 우연히 울려 통과하는 일이 없게 짝을 맞춘다)
INTENDED = {
    "push trigger": "workflow_dispatch", "pull_request trigger": "workflow_dispatch", "pull_request_target": "pull_request_target", "schedule trigger": "workflow_dispatch",
    "workflow_run trigger": "workflow_run", "no trigger": "workflow_dispatch", "inline on list": "workflow_dispatch", "dispatch input": "inputs",
    "write permission": "permissions", "extra permission": "permissions", "no permissions": "permissions", "read-all": "permissions", "job permissions": "permissions",
    "ubuntu runner": "windows-latest", "python 3.11": "3.12", "no timeout": "timeout-minutes", "huge timeout": "timeout-minutes",
    "unpinned checkout": "SHA", "short sha": "SHA", "other sha": "package.yml", "new action": "package.yml", "third party action": "package.yml", "credentials kept": "persist-credentials",
    "secret value": "secrets.", "github token": "github.token", "github.event in run": "주입", "inputs in run": "주입", "context in build run": "주입",
    "two commands in one step": "명령이 하나", "and-and in one step": "명령이 하나", "multi line run": "명령이 하나",
    "no require-hashes (lock)": "--require-hashes", "no require-hashes (build)": "--require-hashes", "no only-binary": "--only-binary", "unpinned install": "--require-hashes", "extra pip step": "--require-hashes",
    "curl download": "외부 접속", "web request": "외부 접속", "no fetch step": "fetch_models", "no require-clean": "--require-clean", "no models-dir": "--models-dir",
    "selftest off": "--no-selftest", "removal off": "--no-remove", "stage not all": "build_ocr_addon.py all", "artifact name": "ChanceBlogDesktop-OCR-preview",
    "extra upload path": "올리는 경로", "work folder upload": "올리는 경로", "wildcard upload": "올리는 경로", "info under old name": "올리는 경로",
    "retention 30": "retention-days", "no retention": "retention-days", "no error on empty": "if-no-files-found", "no upload": "upload-artifact", "two uploads": "upload-artifact",
    "no verify step": "산출물 점검", "verify replaced": "산출물 점검", "verify before build": "산출물 점검", "verify after upload": "산출물 점검", "verify without release": "산출물 점검", "verify with lock": "--lock", "continue on error": "continue-on-error", "step condition": "continue-on-error",
}


class RuleCheckerTest(unittest.TestCase):
    def test_each_bad_variant_is_caught(self):
        for name, text in bad_variants().items():
            with self.subTest(name=name):
                self.assertNotEqual(violations(text, REFS), [], name)

    def test_the_rule_that_was_meant_to_fire_is_the_one_that_fires(self):
        variants = bad_variants()
        self.assertEqual(sorted(variants), sorted(INTENDED), "변형 목록과 낱말 표가 어긋난다")
        for name, text in variants.items():
            with self.subTest(name=name):
                self.assertIn(INTENDED[name], " ".join(violations(text, REFS)), name)

    def test_the_messages_name_the_rule_that_was_broken(self):
        cases = ((mutate("on:\n  workflow_dispatch:\n", "on:\n  workflow_dispatch:\n  push:\n"), "workflow_dispatch"), (mutate("permissions:\n  contents: read\n", "permissions:\n  contents: write\n"), "permissions"),
                 (mutate("actions/checkout@11d5960a326750d5838078e36cf38b85af677262", "actions/checkout@v4"), "SHA"), (mutate("retention-days: 14", "retention-days: 30"), "retention-days"),
                 (mutate("--require-hashes --only-binary=:all: -r ocr_addon/requirements-ocr.lock", "-r ocr_addon/requirements-ocr.lock"), "--require-hashes"),
                 (mutate("actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02", "actions/upload-artifact@" + "0" * 40), "package.yml"))
        for text, word in cases:
            with self.subTest(word=word):
                self.assertIn(word, " ".join(violations(text, REFS)))

    def test_comments_do_not_count_as_secrets_or_write_permissions(self):
        text = REAL.replace("# 단계마다 명령은 하나다", "# secrets.TOKEN write 낱말은 주석 안이면 센 것이 아니다 — 단계마다 명령은 하나다", 1)
        self.assertIn("# secrets.TOKEN write", text)
        self.assertEqual(violations(text, REFS), [])

    def test_crlf_line_endings_do_not_change_the_verdict(self):
        self.assertEqual(violations(REAL.replace("\n", "\r\n"), REFS), [])

    def test_the_reference_set_matters_a_matching_pin_that_package_yml_does_not_use_fails(self):
        self.assertEqual(violations(REAL, REFS), [])
        smaller = {ref for ref in REFS if "upload-artifact" not in ref}
        self.assertNotEqual(violations(REAL, smaller), [])


def bypass_variants():
    """검증자들이 찾은, 금지 낱말 찾기로는 못 잡던 우회 표기와 끼워 넣기(독립 검증 S 의 SP-2·Q 의 QP-3) — 진짜 파일(REAL)을 한 군데씩 바꾼 것.
    값: (글, 구조 규칙이 울려야 하는 낱말, 낱말 규칙이 울려야 하는 낱말 또는 None)."""
    env_block = "    env:\n      PYTHONUTF8: '1'\n"
    checkout_with = "        with:\n          persist-credentials: false\n"
    py_with = "          python-version: '3.12'\n"
    upload_last = "          if-no-files-found: error\n"
    timeout_line = "    timeout-minutes: 45\n"
    fetch_run = 'run: python ocr_addon/fetch_models.py --dest "$env:RUNNER_TEMP/ocr_models"'
    new_step_anchor = "      - name: 설치된 패키지끼리 맞는지 확인"
    flow_anchor = "      - uses: actions/setup-python@"
    perms = "permissions:\n  contents: read\n"

    def env_plus(line):
        return mutate(env_block, env_block + "      " + line + "\n")

    def with_plus(line):
        return mutate(checkout_with, checkout_with + "          " + line + "\n")

    def new_step(run):
        return mutate(new_step_anchor, "      - run: " + run + "\n" + new_step_anchor)

    def flow_step(body):
        return mutate(flow_anchor, "      - " + body + "\n" + flow_anchor)
    S_ENV, S_STEP_KEY, S_LIST, S_READ, S_WITH, S_JOB, S_TOP, S_RUN, S_CONC = ("구조: 작업 env", "구조: 단계 키", "구조: 단계 목록", "구조: 읽을 수 없는 표기", "구조: with", "구조: 작업 키", "구조: 최상위 키", "구조: run", "구조: concurrency")
    def hidden_after(char, where):
        """주석 줄이나 name 칸 안의 줄 나눔 닮은 글자 뒤에 단계를 숨긴다 — libyaml 계열 파서(PyYAML)는 그 글자를 줄 나눔으로 읽어 숨은 단계가 보인다(독립 검증 S 의 SP-6)."""
        hidden = '      - {"run":"python tools/x.py"}'
        if where == "comment":
            return mutate(new_step_anchor, "      # 설명" + char + hidden + "\n" + new_step_anchor)
        return mutate(new_step_anchor, new_step_anchor + char + hidden)
    return {
        # 작업 환경 변수 끼워 넣기(승인 조건 시험이 env 를 안 봤다)
        "job env PIP_INDEX_URL": (env_plus("PIP_INDEX_URL: x"), S_ENV, None), "job env PIP_EXTRA_INDEX_URL": (env_plus("PIP_EXTRA_INDEX_URL: x"), S_ENV, None),
        "job env HTTPS_PROXY": (env_plus("HTTPS_PROXY: x"), S_ENV, None), "job env SSL_CERT_FILE": (env_plus("SSL_CERT_FILE: x"), S_ENV, None), "job env PYTHONPATH": (env_plus("PYTHONPATH: x"), S_ENV, None),
        "step env": (mutate(VERIFY_RUN, "env:\n          K: v\n        " + VERIFY_RUN), S_STEP_KEY, None),
        "top-level env": (mutate(perms, perms + "env:\n  X: y\n"), S_TOP, None),
        # 새 한 줄 명령 단계(외부 접속 도구 낱말 목록 밖)
        "new step python -c": (new_step("python -c \"import urllib.request as u; u.urlopen('x')\""), S_LIST, None), "new step python tool": (new_step("python tools/x.py"), S_LIST, None),
        "new step certutil": (new_step("certutil -urlcache -f x y"), S_LIST, None), "new step bitsadmin": (new_step("bitsadmin /transfer j x y"), S_LIST, None),
        "new step pwsh iex": (new_step("pwsh -c iex x"), S_LIST, None), "new step git remote": (new_step("git remote add origin x"), S_LIST, None),
        "new step appended last": (REAL + "      - run: certutil -urlcache -f x y\n", S_LIST, None),
        # 한 단계에 명령 둘(금지 정규식이 ; && || 만 보던 틈)
        "single ampersand": (mutate(fetch_run, fetch_run + " & python --version"), S_RUN, "명령이 하나"), "pipe": (mutate(fetch_run, fetch_run + " | Out-Null"), S_RUN, "명령이 하나"),
        "sub-expression": (mutate('--dest "$env:RUNNER_TEMP/ocr_models"', '--dest "$env:RUNNER_TEMP/ocr_models" $(Get-Date)'), S_RUN, "명령이 하나"),
        "backtick": (mutate(fetch_run, fetch_run + " " + chr(96) + "x"), S_RUN, "명령이 하나"),
        # 한 줄 흐름식·앵커·겹친 키 같은 다른 표기(읽을 수 없다고 거절한다)
        "flow run step with github.event": (flow_step('{run: "echo ${{ github.event.head_commit.message }}"}'), S_READ, None),
        "flow run step with curl": (flow_step('{run: "curl -O https://example.invalid/x.zip"}'), S_READ, None), "flow uses step": (flow_step("{uses: someone/tool@v1}"), S_READ, "SHA"),
        "flow with": (mutate(checkout_with, "        with: {persist-credentials: false, repository: someone/other}\n"), S_READ, None), "flow env": (mutate(env_block, "    env: {PYTHONUTF8: '1', PIP_INDEX_URL: x}\n"), S_READ, None),
        "yaml anchor": (mutate("  contents: read\n", "  contents: &c read\n"), S_READ, None), "yaml alias": (mutate("  contents: read\n", "  contents: *c\n"), S_READ, None),
        "yaml tag": (mutate("  contents: read\n", "  contents: !!str read\n"), S_READ, None), "yaml merge key": (mutate(perms, perms + "  <<: x\n"), S_READ, None),
        "tab indentation": (mutate(perms, "permissions:\n\tcontents: read\n"), S_READ, None), "second document": (REAL + "---\nname: x\n", S_READ, None),
        "duplicate top-level key": (mutate(perms, perms + perms), S_READ, "permissions"), "duplicate with key": (mutate(checkout_with, checkout_with + "          persist-credentials: true\n"), S_READ, None),
        # with 의 키(persist-credentials 만 보던 틈)
        "checkout repository": (with_plus("repository: someone/other"), S_WITH, None), "checkout ref": (with_plus("ref: ${{ github.head_ref }}"), S_WITH, None),
        "checkout submodules": (with_plus("submodules: recursive"), S_WITH, None), "checkout fetch-depth": (with_plus("fetch-depth: 0"), S_WITH, None),
        "setup-python cache": (mutate(py_with, py_with + "          cache: pip\n"), S_WITH, None), "setup-python check-latest": (mutate(py_with, py_with + "          check-latest: true\n"), S_WITH, None),
        "upload overwrite": (mutate(upload_last, upload_last + "          overwrite: true\n"), S_WITH, None), "upload include-hidden-files": (mutate(upload_last, upload_last + "          include-hidden-files: true\n"), S_WITH, None),
        # 비밀 참조의 다른 쓰기(낱말 secrets. 와 github.token 만 보던 틈)
        "secrets bracket": (with_plus("token: ${{ secrets['KEY'] }}"), S_WITH, "secrets 낱말"), "toJSON secrets": (with_plus("token: ${{ toJSON(secrets) }}"), S_WITH, "secrets 낱말"), "toJSON github context": (with_plus("token: ${{ toJSON(github) }}"), S_WITH, "toJSON"),
        "github bracket token": (with_plus("token: ${{ github['token'] }}"), S_WITH, "github["),
        # 단계·작업·최상위의 다른 키
        "step shell": (mutate(VERIFY_RUN, VERIFY_RUN + "\n        shell: cmd"), S_STEP_KEY, None), "step working-directory": (mutate(VERIFY_RUN, VERIFY_RUN + "\n        working-directory: x"), S_STEP_KEY, None),
        "step id": (mutate(VERIFY_RUN, VERIFY_RUN + "\n        id: x"), S_STEP_KEY, None),
        "job environment": (mutate(timeout_line, timeout_line + "    environment: production\n"), S_JOB, None), "job defaults": (mutate(timeout_line, timeout_line + "    defaults:\n      run:\n        shell: cmd\n"), S_JOB, None),
        "job container": (mutate(timeout_line, timeout_line + "    container: x\n"), S_JOB, None), "job services": (mutate(timeout_line, timeout_line + "    services:\n      s:\n        image: x\n"), S_JOB, None),
        "job needs": (mutate(timeout_line, timeout_line + "    needs: x\n"), S_JOB, None), "top-level defaults": (mutate(perms, perms + "defaults:\n  run:\n    shell: cmd\n"), S_TOP, None),
        "concurrency cancel": (mutate("  cancel-in-progress: false\n", "  cancel-in-progress: true\n"), S_CONC, None), "concurrency group": (mutate("  group: package-ocr-${{ github.ref }}\n", "  group: other\n"), S_CONC, None),
        # 줄 나눔 닮은 글자·보이지 않는 글자로 주석·name 칸에 숨기기(읽개가 거절한다)
        "comment hides a step after U+2028": (hidden_after(chr(0x2028), "comment"), S_READ, None), "comment hides a step after U+2029": (hidden_after(chr(0x2029), "comment"), S_READ, None),
        "comment hides a step after U+0085": (hidden_after(chr(0x85), "comment"), S_READ, None), "name hides a step after U+2028": (hidden_after(chr(0x2028), "name"), S_READ, None),
        "name hides a step after U+2029": (hidden_after(chr(0x2029), "name"), S_READ, None), "name hides a step after U+0085": (hidden_after(chr(0x85), "name"), S_READ, None),
        "comment with vertical tab": (hidden_after(chr(0x0B), "comment"), S_READ, None), "comment with form feed": (hidden_after(chr(0x0C), "comment"), S_READ, None),
        "comment with right-to-left override": (mutate(new_step_anchor, "      # 설명" + chr(0x202E) + "뒤집힌 글\n" + new_step_anchor), S_READ, None),
        "name with zero width space": (mutate(new_step_anchor, new_step_anchor + chr(0x200B)), S_READ, None),
        "private use character in a comment": (mutate(new_step_anchor, "      # " + chr(0xE000) + "\n" + new_step_anchor), S_READ, None),
    }


class BypassRuleTest(unittest.TestCase):
    """독립 검증 S 의 SP-2·Q 의 QP-3 — 금지 낱말 찾기가 놓치던 우회 표기와 끼워 넣기가 이제 '글을 구조로 읽는' 규칙에 걸린다(허용 목록 방식)."""

    def test_every_bypass_variant_is_caught_by_the_structure_rule_alone_with_its_reason(self):
        variants = bypass_variants()
        self.assertEqual(len(variants), 65, "문서(결정 D-532)에 적힌 우회 변형 수와 같다 — 변형을 더하거나 빼면 문서의 숫자도 같이 고친다")
        for name, (text, structure_word, _keyword_word) in variants.items():
            with self.subTest(name=name):
                problems = structure_problems(text, REFS)
                self.assertNotEqual(problems, [], name)
                self.assertIn(structure_word, " ".join(problems), name)

    def test_the_whole_checker_reports_every_variant_and_the_keyword_reason_where_there_is_one(self):
        for name, (text, _structure_word, keyword_word) in bypass_variants().items():
            with self.subTest(name=name):
                everything = violations(text, REFS)
                self.assertNotEqual(everything, [], name)
                keyword_only = " ".join(item for item in everything if not item.startswith("구조:"))      # 구조 규칙의 글에는 변형의 글이 그대로 들어가므로 낱말 규칙의 글만 본다
                if keyword_word:
                    self.assertIn(keyword_word, keyword_only, name)

    def test_the_structure_rule_alone_also_catches_every_one_of_the_older_bad_variants(self):
        """앞서의 나쁜 변형 62개는 낱말 규칙이 잡았는데, 구조 규칙(허용 목록)도 같은 변형을 하나도 놓치지 않는다 — 두 규칙이 서로 다른 그물이다."""
        variants = bad_variants()
        self.assertGreaterEqual(len(variants), 60)
        for name, text in variants.items():
            with self.subTest(name=name):
                self.assertNotEqual(structure_problems(text, REFS), [], name)

    def test_the_real_workflow_passes_and_crlf_and_comment_text_do_not_matter(self):
        self.assertEqual(structure_problems(REAL, REFS), [])
        self.assertEqual(structure_problems(REAL.replace("\n", "\r\n"), REFS), [])
        quiet = REAL.replace("# 단계마다 명령은 하나다", "# 주석 안의 {run: x} &anchor *alias secrets['K'] 는 읽지 않는다 — 단계마다 명령은 하나다", 1)
        self.assertIn("# 주석 안의", quiet)
        self.assertEqual(structure_problems(quiet, REFS), [])
        self.assertEqual(violations(quiet, REFS), [])

    def test_the_structure_rule_needs_the_reference_pins_too(self):
        smaller = {ref for ref in REFS if "upload-artifact" not in ref}
        self.assertTrue(any("구조: 액션" in item for item in structure_problems(REAL, smaller)))

    def test_the_expected_steps_table_is_the_real_file_step_for_step(self):
        steps = yamlsub.load(REAL)["jobs"][JOB_NAME]["steps"]
        self.assertEqual(len(steps), len(EXPECTED_STEPS))
        for step, expected in zip(steps, EXPECTED_STEPS):
            if expected[0] == "run":
                self.assertEqual(step["run"], expected[1])
            else:
                self.assertEqual((step["uses"].split("@")[0], step["with"]), (expected[1], expected[2]))

    def test_one_command_counts_a_single_ampersand_a_pipe_a_subexpression_and_a_backtick_as_two_commands(self):
        for good in ('python ocr_addon/verify_release.py --release "$env:RUNNER_TEMP/ocr/release"', '& "$env:RUNNER_TEMP/x/python.exe" -m pip check', "python -m pip install --only-binary=:all: -r a.txt", 'Get-Content "a;b|c&d"'):
            self.assertTrue(one_command(good), good)
        for bad in ("a & b", "a | b", "a; b", "a && b", "a || b", "a $(b)", "a " + chr(96) + "b", '& "x" & y'):
            self.assertFalse(one_command(bad), bad)


if __name__ == "__main__":
    unittest.main()
