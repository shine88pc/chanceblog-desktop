"""설치 도구 시험(spike) 시험 도우미(시험이 아니다) — `packaging/spike/` 의 스크립트를 파일 경로로 불러오고, 수동 워크플로 `installer-spike.yml` 의 규칙 검사기(`violations`)를 담는다(결정 D-700).

`packaging/spike/` 는 앱 묶음 밖 폴더라 import 경로에 없다. 이 도우미는 불러오는 동안에만 그 폴더를 `sys.path` 맨 앞에 두고(형제 파일 가져오기용) 곧 뺀다 — `measure`·`fetch_tools` 같은 이름이
다른 시험에 새지 않게 `sys.modules` 의 형제 이름도 치운다. 시험은 표준 라이브러리만 쓰고 PyInstaller·vpk·Inno Setup·윈도 없이 돈다(윈도에서만 도는 부분은 시험이 건너뛰기 표시를 한다).
"""
import importlib.util
import re
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_workflow_artifacts as wf  # noqa: E402  (단계·`uses:`·업로드 경로를 읽는 같은 도우미)
import workflow_yaml_support as yamlsub  # noqa: E402  (글을 구조로 읽는 작은 읽개 — 표준 라이브러리만)

ROOT = Path(__file__).resolve().parent.parent
SPIKE = ROOT / "packaging" / "spike"
WORKFLOW = ROOT / ".github" / "workflows" / "installer-spike.yml"
REFERENCE = ROOT / ".github" / "workflows" / "package.yml"
_LOADED = {}
_SIBLINGS = ("fetch_tools", "measure", "run_spike", "spike_app", "spike_app_sdk")


def load(name):
    """`packaging/spike/<name>.py` 를 한 번만 불러와 돌려준다(모듈 이름은 `installer_spike_<name>`)."""
    if name not in _LOADED:
        sys.path.insert(0, str(SPIKE))
        # `packaging/` 의 기존 도구(make_manifest·pkgcommon·build_package)를 스크립트가 같이 쓴다 — 불러오는 동안만 경로에 둔다
        sys.path.insert(1, str(ROOT / "packaging"))
        try:
            spec = importlib.util.spec_from_file_location("installer_spike_" + name, str(SPIKE / (name + ".py")))
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)
        finally:
            sys.path.remove(str(SPIKE))
            sys.path.remove(str(ROOT / "packaging"))
            for sibling in _SIBLINGS:
                if sibling != name:
                    sys.modules.pop(sibling, None)
        _LOADED[name] = module
    return _LOADED[name]


def read(rel):
    """저장소 안 글 파일을 줄 끝(CRLF·LF)과 상관없이 읽는다."""
    return (ROOT / rel).read_text(encoding="utf-8").replace("\r\n", "\n")


SHA_REF = re.compile(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}")

# ---- 수동 워크플로 `installer-spike.yml` 의 규칙 검사기 ------------------------------------------------------------------------------------
# 글을 '구조'로 읽어(`workflow_yaml_support` — 흐름식·앵커·겹친 키 같은 표기는 읽을 수 없다고 거절) 승인 조건(운영자 확인 037 ①)을 허용 목록으로 견준다. 금지 낱말 찾기가 놓치는 우회 표기를 막는다.

ARTIFACT_NAME = "InstallerSpike-report"
UPLOAD_PATHS = ("spike/report/INSTALLER_SPIKE_REPORT.md", "spike/report/INSTALLER_SPIKE_REPORT.json")
ACTION_NAMES = {"actions/checkout", "actions/setup-python", "actions/upload-artifact"}
NETWORK_TOOLS = ("curl", "wget", "Invoke-WebRequest", "Invoke-RestMethod", "iwr ", "irm ", "Start-BitsTransfer", "git clone", "git fetch", "git pull", "npm ", "choco ", "winget ", "dotnet tool", "nuget ", "scoop ")
JOB_NAME = "installer-spike"
TOP_KEYS = {"name", "on", "permissions", "concurrency", "jobs"}
JOB_KEYS = {"name", "runs-on", "timeout-minutes", "env", "steps"}
STEP_KEYS = {"name", "uses", "with", "run"}
JOB_ENV = {"PYTHONUTF8": "1", "DOTNET_CLI_TELEMETRY_OPTOUT": "1", "DOTNET_NOLOGO": "1"}
CONCURRENCY = {"group": "installer-spike-${{ github.ref }}", "cancel-in-progress": "false"}
SPIKE_COMMANDS = ("install-tools", "build-bundles", "pack", "measure", "report")
WORK_ARG = '--work "$env:RUNNER_TEMP/spike"'
# 이 흐름의 열 단계 — 허용 목록이다. 단계를 더하거나 빼거나 명령·with 를 바꾸려면 이 목록(과 시험)을 같이 고쳐야 하므로 운영자 눈에 띈다.
EXPECTED_STEPS = (
    ("uses", "actions/checkout", {"persist-credentials": "false"}),
    ("uses", "actions/setup-python", {"python-version": "3.12"}),
    ("run", "python -m pip install -r packaging/requirements-package.txt"),
    ("run", 'python packaging/spike/fetch_tools.py --dest "$env:RUNNER_TEMP/spike/tools"'),
    ("run", "python packaging/spike/run_spike.py install-tools " + WORK_ARG),
    ("run", "python packaging/spike/run_spike.py build-bundles " + WORK_ARG),
    ("run", "python packaging/spike/run_spike.py pack " + WORK_ARG),
    ("run", "python packaging/spike/run_spike.py measure " + WORK_ARG),
    ("run", "python packaging/spike/run_spike.py report " + WORK_ARG),
    ("uses", "actions/upload-artifact", {"name": ARTIFACT_NAME, "path": "".join("${{ runner.temp }}/" + path + "\n" for path in UPLOAD_PATHS), "retention-days": "14", "if-no-files-found": "error"}),
)


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
    return re.findall(r"\buses:\s*([^\s,}#]+)", code_of(text))                       # 한 줄 흐름식 `- {uses: …}` 안의 것도 찾는다


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
        problems.append(f"구조: 단계 키 — 단계 {position} 에 허용되지 않은 키가 있다(env·shell·if·continue-on-error·working-directory 같은 키를 못 끼운다): {extra}")
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
        elif not (isinstance(step.get("name"), str) and step["name"].strip()):
            problems.append(f"구조: 단계 키 — 단계 {position} 에 name 이 없다(단계마다 이름을 붙여 로그가 갈리게 한다)")
    return problems


def structure_problems(text, reference_refs):
    """글을 '구조'로 읽어 승인 조건을 허용 목록으로 견준다 — 금지 낱말 찾기가 놓치는 우회 표기를 막는다."""
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
        return problems + [f"구조: 작업 키 — 정해진 다섯({sorted(JOB_KEYS)})과 다르다(environment·container·services·defaults·permissions·strategy 같은 키를 못 끼운다): {sorted(job) if isinstance(job, dict) else type(job).__name__}"]
    if job["runs-on"] != "windows-latest" or not re.fullmatch(r"[1-9]|[1-5][0-9]|60", str(job["timeout-minutes"])):
        problems.append("구조: 작업 값 — runs-on 은 windows-latest, timeout-minutes 는 1에서 60 이어야 한다")
    if job["env"] != JOB_ENV:
        problems.append(f"구조: 작업 env — 정해진 셋({sorted(JOB_ENV)})이어야 한다(PIP_INDEX_URL·프록시·인증서·경로·NUGET 환경 변수를 못 끼운다): {job['env']!r}")
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
    if not re.search(r"^\s*timeout-minutes:\s*(?:[1-9]|[1-5][0-9]|60)\s*$", code, re.M):
        problems.append("timeout-minutes 가 1에서 60 사이가 아니다")
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
            if not re.fullmatch(r"python -m pip install -r packaging/requirements-package\.txt", body.strip()):
                problems.append(f"pip 설치가 잠금 파일(packaging/requirements-package.txt) 한 줄이 아니다: {body.strip()[:60]}")
    joined = "\n".join(bodies)
    scripts = re.findall(r"packaging/spike/([A-Za-z_]+\.py)", joined)
    if sorted(set(scripts)) != ["fetch_tools.py", "run_spike.py"]:
        problems.append(f"실행하는 시험 스크립트는 fetch_tools.py 와 run_spike.py 둘뿐이다: {sorted(set(scripts))}")
    for command in SPIKE_COMMANDS:
        if len(re.findall(rf"run_spike\.py {re.escape(command)} ", joined)) != 1:
            problems.append(f"run_spike.py {command} 가 정확히 한 번이어야 한다")
    if joined.count("packaging/spike/fetch_tools.py --dest") != 1 or "--lock" in joined:
        problems.append("도구 받기는 `fetch_tools.py --dest 폴더` 한 단계여야 한다(잠금 파일을 바꿔 끼우는 --lock 이 없다)")
    for word in ("--skip", "--allow", "--no-verify", "--insecure", "--trusted-host", "--index-url", "--extra-index-url", "--no-check", "--force-reinstall"):
        if word in joined:
            problems.append(f"점검·검증을 끄거나 다른 곳으로 돌리는 옵션 낱말: {word}")
    if re.search(r"(?m)^\s+(?:-\s+)?(?:if|continue-on-error):", code):
        problems.append("단계에 if·continue-on-error 가 있다 — 실패한 단계를 건너뛰어 초록으로 끝나는 길이 된다")
    steps = wf.steps_of(text)
    run_of = [wf.block_after(step, "run") for step in steps]
    order = [next((index for index, body in enumerate(run_of) if f"run_spike.py {command} " in body), -1) for command in SPIKE_COMMANDS]
    fetch_at = next((index for index, body in enumerate(run_of) if "fetch_tools.py" in body), -1)
    upload_at = [index for index, step in enumerate(steps) if wf.UPLOAD_ACTION.search(wf.uses_of(step))]
    if not (0 <= fetch_at < min(order) and order == sorted(order) and len(set(order)) == len(order) and len(upload_at) == 1 and upload_at[0] > max(order)):
        problems.append("순서가 도구 받기, install-tools, build-bundles, pack, measure, report, 올리기 가 아니다")
    uploads = wf.upload_steps(text)
    if len(uploads) != 1:
        problems.append(f"upload-artifact 가 정확히 한 번이어야 한다({len(uploads)})")
    for _number, step in uploads:
        if not re.search(rf"^\s*name:\s*{re.escape(ARTIFACT_NAME)}\s*$", step, re.M):
            problems.append(f"올리는 산출물 이름은 {ARTIFACT_NAME} 이어야 한다")
        entries = [item.replace("${{ runner.temp }}/", "") for item in wf.upload_paths(step)]
        if entries != list(UPLOAD_PATHS):
            problems.append(f"올리는 경로가 정해진 둘(보고서 md·json)이 아니다: {entries}")
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


# ---- 합성 PE(시험용) ------------------------------------------------------------------------------------------------------------------------

def build_pe(imports=(), delay=(), plus=True, manifest=None):
    """가져오기 표를 가진 가장 작은 PE 파일(바이트) — 시험용 합성이다."""
    data = bytearray(0x1000)
    data[0:2] = b"MZ"
    struct.pack_into("<I", data, 0x3C, 0x80)
    data[0x80:0x84] = b"PE\x00\x00"
    optional_size = 240 if plus else 224
    struct.pack_into("<HHIIIHH", data, 0x84, 0x8664 if plus else 0x14C, 1, 0, 0, 0, optional_size, 0x22)
    optional = 0x98
    struct.pack_into("<H", data, optional, 0x20B if plus else 0x10B)
    directory_at = optional + (112 if plus else 96)
    struct.pack_into("<I", data, directory_at - 4, 16)
    section_at = optional + optional_size
    data[section_at:section_at + 8] = b".idata\x00\x00"
    struct.pack_into("<IIII", data, section_at + 8, 0x800, 0x2000, 0x800, 0x400)
    raw, base_rva = 0x400, 0x2000
    cursor = 0x400 + 0x300                                  # 이름 글을 두는 자리(앞쪽 0x300 은 표용)
    names_at = {}
    for name in list(imports) + list(delay):
        names_at[name] = cursor
        data[cursor:cursor + len(name) + 1] = name.encode("ascii") + b"\x00"
        cursor += len(name) + 2

    def rva_of(offset):
        return base_rva + (offset - raw)

    table = raw
    for name in imports:
        struct.pack_into("<IIIII", data, table, 0, 0, 0, rva_of(names_at[name]), 0)
        table += 20
    import_size = table + 20 - raw
    delay_table = raw + 0x180
    for name in delay:
        struct.pack_into("<IIIIIIII", data, delay_table, 1, rva_of(names_at[name]), 0, 0, 0, 0, 0, 0)
        delay_table += 32
    if imports:
        struct.pack_into("<II", data, directory_at + 8, rva_of(raw), import_size)
    if delay:
        struct.pack_into("<II", data, directory_at + 8 * 13, rva_of(raw + 0x180), len(delay) * 32 + 32)
    if manifest:
        data[0xE00:0xE00 + len(manifest)] = manifest
    return bytes(data)


# ---- 읽은 변수를 적어 두는 환경 사전(시험용) ------------------------------------------------------------------------------------------------

class RecordingEnv(dict):
    """읽힌 열쇠를 모아 두는 환경 사전 — 러너 가드가 실제로 어느 환경 변수를 읽는지 본다(문서가 말하는 변수 이름과 코드가 읽는 이름이 같은지 견주는 시험이 쓴다). `read_keys` 에 읽은 순서대로 쌓인다."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.read_keys = []

    def get(self, key, default=None):
        self.read_keys.append(key)
        return super().get(key, default)

    def __getitem__(self, key):
        self.read_keys.append(key)
        return super().__getitem__(key)

    def __contains__(self, key):
        self.read_keys.append(key)
        return super().__contains__(key)
