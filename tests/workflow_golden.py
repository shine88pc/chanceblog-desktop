# -*- coding: utf-8 -*-
"""`ci.yml`·`package.yml` 을 글을 '구조'로 읽어 승인된 모양과 글자 그대로 견주는 허용 목록 규칙 — AS-S2 권고-7(결정 D-693).

왜: 감사(공급망 탐침)에서 안전 장치를 약하게 만든 사본 11개가 기존 시험을 모두 통과했다 — 작업 단위 `permissions` 에 쓰기 권한·액션의 소유자나 저장소 이름·SHA 값 바꾸기·`persist-credentials: true`·
matrix 에 `self-hosted`·작업 단위 `env` 에 `PYTHONPATH`(이상 `ci.yml`), 다른 `run` 단계(내려받기 명령)·한 줄 흐름식 단계로 태그 액션·`pip --extra-index-url`·빌드 명령을 문자열 출력으로 바꾸기·`persist-credentials: true`
(이상 `package.yml`). 기존 시험은 낱말·정규식 검사였고(액션은 '40자리 16진수로 끝나는가' 만 봤다) `package-ocr.yml` 만 단계 열한 개를 글자 그대로 못박았다(`tests/test_package_ocr_workflow.py`).
이 모듈은 같은 방식(`tests/workflow_yaml_support.py` 의 작은 읽개 — 흐름식·앵커·겹친 키 같은 표기는 읽을 수 없다고 거절)을 두 파일에도 적용한다: 최상위·작업·단계 키와 `with`·`env`·`run` 값이 승인된 목록과 **같아야** 하고,
액션은 승인된 `소유자/저장소@커밋` 쌍(아래 `ACTIONS`)뿐이다. 단계를 더하거나 빼거나 명령·`with` 를 바꾸거나 액션의 SHA 를 갱신하려면 이 목록(과 시험)을 같이 고쳐야 하므로 운영자 눈에 띈다 —
`.github/` 의 변경은 어차피 T3(운영자 승인)이고, 이 시험이 그 승인에 '무엇이 바뀌었는가' 를 글자 단위로 남긴다. 이 파일은 `.github/` 를 읽기만 한다(고치지 않는다).
`ci.yml` 의 matrix 줄(`os: [ubuntu-latest, windows-latest]` 같은 한 줄 목록)은 읽개가 거절하는 표기라, **정해진 세 줄(들여쓰기 8칸의 os·python·shard)만** 따옴표 글로 바꿔 읽는다 — 다른 곳의 흐름식은 그대로 거절된다.

여러 작업(D-716): `ci.yml` 은 작업이 둘이다 — `test`(열두 칸, 승인값은 D-693 때 그대로)와 `qt`(윈도·파이썬 3.12 의 Qt 칸, D-710–D-713). 명세의 `jobs` 가 작업의 이름·순서·개수를 못박고(작업을 더하거나 빼거나 이름·순서를 바꾸면 문제다) 작업마다 키 집합·`runs-on`·`timeout-minutes`·`strategy`·`env`·단계를
승인값과 견준다. `qt` 작업은 `name` 도 글자 그대로 못박고 시간 한도는 정확히 60분이다(`test` 잡의 40분과 다르다 — 4차 진단에서 가장 느린 조각이 설치까지 약 33분이라 40분은 빠듯해 운영자 확인 046 ① 이 올렸다, D-717. `auto-pr.yml` 의 최대 대기 60분과 같은 값이다 — D-719, `tests/test_ci_workflow_qt.py`). `test` 작업은 D-693 의 값(시간 한도 범위 포함)을 그대로 둔다.
문제 글에는 `작업 <이름>:` 을 앞에 붙여 어느 작업이 어긋났는지 보이게 한다. 두 작업의 승인값 표는 `tests/test_workflow_golden.py` 가 한 번 더 글자 그대로 못박는다(표를 슬쩍 느슨하게 고치면 그 시험이 빨개진다).

D-717·D-718(Qt 칸 마무리): `qt` 작업의 승인값이 바뀌었다 — 조각 열둘(`shard` 목록·`CI_SHARD_TOTAL`·이름의 `/12`)·Qt 칸 전용 무게 표를 고르는 환경 변수 `CI_WEIGHTS: qt`·작업 수준 `if`(`QT_IF`: 병합 가지 `ai/claude/M…` 와 main 에서만 돈다, 글자 그대로).
`test` 작업은 한 글자도 안 바뀌었다(작업 키에 `if` 가 없다 — 열두 칸은 모든 가지에서 돈다). `if` 가 승인된 글과 한 글자라도 다르면(진단 가지 이름을 더하거나 `true`·`always()` 로 바꾸는 것 포함) 작업 문제로 거절한다.

재작업 2(2026-11-26, 4차 진단 — 운영자 확인 046 ①): `qt` 작업의 `timeout-minutes` 승인값이 40 에서 60 으로 바뀌었다(위). 그리고 `if` 줄은 값만이 아니라 줄 전체가 글자 그대로여야 한다 — 줄 끝에 주석이나 공백을 달아도 거절한다
(읽개는 줄 끝 주석을 값으로 보지 않아 예전에는 통과했지만, 이 줄은 Qt 칸이 도는 가지를 정하므로 다른 시험 묶음(`test_repo_layout`·`test_ci_workflow_qt`·`test_ci_shard`)이 쓰는 엄격한 잣대에 맞췄다 — 독립 검증 Q 권고-5).
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import workflow_yaml_support as yamlsub  # noqa: E402

# 승인된 액션 — `소유자/저장소` → 커밋 SHA. 갱신은 같은 메이저 안의 최신 태그를 눈으로 확인한 뒤 이 표와 `.github/` 를 함께 바꾼다(운영자 승인, `docs/SECURITY.md` §4).
ACTIONS = {
    "actions/checkout": "11d5960a326750d5838078e36cf38b85af677262",
    "actions/setup-python": "a26af69be951a213d495a4c3e4e4022e16d87065",
    "actions/upload-artifact": "ea165f8d65b6e75b540449e92b4886f43607fa02",
}
APPROVED_REFS = frozenset(f"{name}@{sha}" for name, sha in ACTIONS.items())
TOP_KEYS = {"name", "on", "permissions", "concurrency", "jobs"}
STEP_KEYS = {"name", "uses", "with", "run", "env"}
MATRIX_LINE = re.compile(r"(?m)^(        (?:os|python|shard)):[ ]+(\[[^\]\n]*\])[ ]*$")
USES = re.compile(r"\buses:\s*([^\s,}#]+)")

CI_STEPS = (
    ("uses", "actions/checkout", {"persist-credentials": "false"}, None),
    ("uses", "actions/setup-python", {"python-version": "${{ matrix.python }}"}, None),
    ("run", "python scripts/ci_shard.py", None, {"PYTHONUTF8": "1", "CI_SHARD": "${{ matrix.shard }}", "CI_SHARD_TOTAL": "3"}),
)
CI_TEST_JOB = {          # D-693 때의 승인값 그대로 — 바뀐 것은 이 값이 `CI["jobs"]` 안으로 들어간 것뿐이다(작업 이름 값은 그때도 못박지 않았다)
    "job_keys": {"name", "runs-on", "timeout-minutes", "strategy", "steps"},
    "runs_on": "${{ matrix.os }}",
    "timeout": re.compile(r"4[0-9]|5[0-9]|60"),
    "strategy": {"fail-fast": "false", "matrix": {"os": "[ubuntu-latest, windows-latest]", "python": "['3.10', '3.12']", "shard": "[1, 2, 3]"}},
    "env": None,
    "steps": CI_STEPS,
}
CI_QT_STEPS = (
    ("uses", "actions/checkout", {"persist-credentials": "false"}, None),
    ("uses", "actions/setup-python", {"python-version": "3.12"}, None),
    ("run", "python scripts/ci_qt_setup.py", None, None),
    ("run", "python scripts/ci_shard.py", None, {"PYTHONUTF8": "1", "CI_SHARD": "${{ matrix.shard }}", "CI_SHARD_TOTAL": "12", "CI_WEIGHTS": "qt", "CI_REQUIRE_QT": "1", "QT_QPA_PLATFORM": "offscreen"}),
)
QT_IF = "github.ref == 'refs/heads/main' || startsWith(github.ref, 'refs/heads/ai/claude/M')"        # D-718 — 병합 가지(ai/claude/M…)와 main 에서만 돈다. 작업 중 가지(NO-MERGE-…)에서는 건너뛴다
CI_QT_JOB = {            # D-716 — `ci.yml` 끝의 둘째 잡(D-710–D-713)을 글자 그대로 못박는다. D-717: 조각 열둘·무게 표, D-718: 돌 때 조건
    "name": "Qt 시험 (windows-latest, Python 3.12, 조각 ${{ matrix.shard }}/12)",
    "if": QT_IF,
    "job_keys": {"name", "if", "runs-on", "timeout-minutes", "strategy", "steps"},
    "runs_on": "windows-latest",
    "timeout": re.compile(r"60"),
    "strategy": {"fail-fast": "false", "matrix": {"shard": "[1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]"}},
    "env": None,
    "steps": CI_QT_STEPS,
}
CI = {
    "on": {"push": None, "workflow_dispatch": None},
    "permissions": {"contents": "read"},
    "concurrency": {"group": "ci-${{ github.event_name }}-${{ github.ref }}", "cancel-in-progress": "true"},
    "jobs": {"test": CI_TEST_JOB, "qt": CI_QT_JOB},            # 작업의 이름·순서·개수까지 못박는다(파일에 나오는 순서)
}
UPLOAD_PATH = "".join("${{ runner.temp }}/package/release/" + leaf + "\n" for leaf in ("ChanceBlogDesktop-*-win64.zip", "SHA256SUMS", "PACKAGE_INFO.md", "PACKAGE_INFO.json"))
PACKAGE_STEPS = (
    ("uses", "actions/checkout", {"persist-credentials": "false"}, None),
    ("uses", "actions/setup-python", {"python-version": "3.12"}, None),
    ("run", "python -m pip install -r packaging/requirements-package.txt", None, None),
    ("run", 'python packaging/build_package.py --out-dir "$env:RUNNER_TEMP/package"', None, None),
    ("run", 'Get-Content "$env:RUNNER_TEMP/package/release/SHA256SUMS"', None, None),
    ("uses", "actions/upload-artifact", {"name": "ChanceBlogDesktop-preview", "path": UPLOAD_PATH, "retention-days": "14", "if-no-files-found": "error"}, None),
)
PACKAGE_JOB = {
    "job_keys": {"name", "runs-on", "timeout-minutes", "env", "steps"},
    "runs_on": "windows-latest",
    "timeout": re.compile(r"[1-9]|[1-3][0-9]|4[0-5]"),
    "strategy": None,
    "env": {"PYTHONUTF8": "1"},
    "steps": PACKAGE_STEPS,
}
PACKAGE = {
    "on": {"workflow_dispatch": None},
    "permissions": {"contents": "read"},
    "concurrency": {"group": "package-${{ github.ref }}", "cancel-in-progress": "false"},
    "jobs": {"package": PACKAGE_JOB},
}


def all_action_refs(text):
    """글 안의 모든 `uses:` 값 — 한 줄 흐름식 `- {uses: …}` 안의 것도 찾는다(줄 맨 앞의 `uses:` 만 보는 검사를 피하는 표기)."""
    code = "\n".join(line for line in text.replace("\r\n", "\n").split("\n") if not line.lstrip().startswith("#"))
    return USES.findall(code)


def action_problems(text):
    """글 안의 모든 액션이 승인된 `소유자/저장소@커밋` 쌍인가 — 다른 소유자·다른 저장소·다른 SHA·태그가 하나라도 있으면 그 목록."""
    return [f"승인된 액션·SHA 가 아니다: {ref}" for ref in all_action_refs(text) if ref not in APPROVED_REFS]


def _step_problems(position, step, expected):
    problems = []
    if not isinstance(step, dict):
        return [f"단계 {position} 가 매핑이 아니다"]
    extra = sorted(set(step) - STEP_KEYS)
    if extra:
        problems.append(f"단계 {position} 에 허용되지 않은 키가 있다(if·shell·continue-on-error·working-directory 같은 키를 못 끼운다): {extra}")
    if "name" in step and not (isinstance(step["name"], str) and step["name"].strip()):
        problems.append(f"단계 {position} 의 name 이 비어 있다")
    kind, target, with_, env = expected
    if kind == "uses":
        ref = step.get("uses")
        if "run" in step or not isinstance(ref, str):
            return problems + [f"단계 {position} 는 uses({target}) 단계여야 한다"]
        if ref != f"{target}@{ACTIONS[target]}":
            problems.append(f"단계 {position} 의 액션이 승인된 `{target}@커밋` 이 아니다: {ref}")
        if step.get("with") != with_:
            problems.append(f"단계 {position} 의 with 가 승인된 것과 다르다(키 하나도 더하거나 바꾸지 못한다): {step.get('with')!r}")
        if "env" in step:
            problems.append(f"단계 {position} 에 env 가 있다(액션 단계에는 환경 변수를 못 끼운다)")
    else:
        if "uses" in step or "with" in step or step.get("run") != target:
            problems.append(f"단계 {position} 의 run 명령이 승인된 글과 다르다: {str(step.get('run'))[:80]!r}")
        if step.get("env") != env:
            problems.append(f"단계 {position} 의 env 가 승인된 것과 다르다(환경 변수 하나도 더하거나 바꾸지 못한다): {step.get('env')!r}")
    return problems


def _job_problems(job_id, job, spec, raw_lines=()):
    """작업 하나(`jobs.<job_id>`)를 승인된 모양(`spec`)과 견준 문제 목록 — 문제 글 앞에 `작업 <이름>:` 을 붙여 어느 작업이 어긋났는지 보이게 한다(작업이 둘이다, D-716)."""
    label = f"작업 {job_id}: "
    if not isinstance(job, dict) or set(job) != spec["job_keys"]:
        return [label + f"작업 키가 정해진 것({sorted(spec['job_keys'])})과 다르다(permissions·env·container·services·defaults·if·needs 같은 키를 못 끼운다): {sorted(job) if isinstance(job, dict) else type(job).__name__}"]
    problems = []
    if "name" in spec and job["name"] != spec["name"]:
        problems.append(label + f"작업 name 이 승인된 글 {spec['name']!r} 와 다르다: {job['name']!r}")
    if "if" in spec and job["if"] != spec["if"]:
        problems.append(label + f"작업 if 가 승인된 글 {spec['if']!r} 와 다르다(이 조건이 Qt 칸을 병합 가지와 main 에서만 돌게 한다 — 진단 가지 이름을 더하거나 true·always() 로 바꾸지 못한다): {job['if']!r}")
    elif "if" in spec and "    if: " + spec["if"] not in raw_lines:
        problems.append(label + f"작업 if 줄이 승인된 한 줄 그대로가 아니다(값은 같아도 줄 끝 주석·뒤 공백 같은 덧붙임을 못 단다 — 이 줄은 Qt 칸이 도는 가지를 정하므로 줄 전체를 글자 그대로 견준다): {spec['if']!r}")
    if job["runs-on"] != spec["runs_on"] or not spec["timeout"].fullmatch(str(job["timeout-minutes"])):
        problems.append(label + f"runs-on 은 {spec['runs_on']!r}, timeout-minutes 는 정해진 범위여야 한다: {job['runs-on']!r} {job['timeout-minutes']!r}")
    if spec["strategy"] is not None and job.get("strategy") != spec["strategy"]:
        problems.append(label + f"strategy(matrix)가 승인된 값과 다르다(self-hosted·include·exclude 를 못 끼운다): {job.get('strategy')!r}")
    if spec["env"] is not None and job.get("env") != spec["env"]:
        problems.append(label + f"작업 env 가 승인된 값과 다르다(PIP_INDEX_URL·PYTHONPATH·프록시 같은 환경 변수를 못 끼운다): {job.get('env')!r}")
    steps = job["steps"]
    expected = spec["steps"]
    if not isinstance(steps, list) or len(steps) != len(expected):
        problems.append(label + f"단계 목록이 승인된 {len(expected)} 단계와 다르다({len(steps) if isinstance(steps, list) else type(steps).__name__}) — 단계를 더하거나 빼려면 이 허용 목록과 시험을 같이 고친다")
    else:
        for position, (step, wanted) in enumerate(zip(steps, expected), 1):
            problems += [label + problem for problem in _step_problems(position, step, wanted)]
    return problems


def structure_problems(text, spec):
    """글을 구조로 읽어 `spec`(CI 또는 PACKAGE)과 견준 문제 목록(없으면 빈 목록). 읽을 수 없는 표기도 문제로 돌려준다(예외를 내지 않는다)."""
    text = text.replace("\r\n", "\n")
    if spec is CI:
        text = MATRIX_LINE.sub(lambda match: match.group(1) + ': "' + match.group(2).replace("\\", "\\\\").replace('"', '\\"') + '"', text)
    try:
        tree = yamlsub.load(text)
    except yamlsub.YamlSubsetError as error:
        return [f"읽을 수 없는 표기 — {error}"]
    if not isinstance(tree, dict) or set(tree) != TOP_KEYS:
        return [f"최상위 키가 정해진 다섯({sorted(TOP_KEYS)})과 다르다: {sorted(tree) if isinstance(tree, dict) else type(tree).__name__}"]
    problems = []
    for key in ("on", "permissions", "concurrency"):
        if tree[key] != spec[key]:
            problems.append(f"{key} 가 승인된 값과 다르다: {tree[key]!r}")
    jobs = tree["jobs"]
    wanted_jobs = list(spec["jobs"])
    if not isinstance(jobs, dict) or list(jobs) != wanted_jobs:
        return problems + [f"작업 목록이 승인된 {wanted_jobs}(이름·순서·개수 모두)와 다르다 — 작업을 더하거나 빼거나 이름·순서를 바꾸려면 이 허용 목록과 시험을 같이 고친다: {list(jobs) if isinstance(jobs, dict) else type(jobs).__name__}"]
    raw_lines = text.split("\n")                      # 줄 전체를 글자 그대로 견주는 곳(작업 if 줄)이 쓴다 — 읽개는 줄 끝 주석을 값으로 보지 않는다
    for job_id, job_spec in spec["jobs"].items():
        problems += _job_problems(job_id, jobs[job_id], job_spec, raw_lines)
    problems += action_problems(text)
    return problems


def ci_problems(text):
    return structure_problems(text, CI)


def package_problems(text):
    return structure_problems(text, PACKAGE)
