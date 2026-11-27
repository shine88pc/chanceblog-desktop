# -*- coding: utf-8 -*-
"""`ci.yml`·`package.yml` 을 글을 '구조'로 읽어 승인된 모양과 글자 그대로 견주는 허용 목록 규칙 — AS-S2 권고-7(결정 D-693).

왜: 감사(공급망 탐침)에서 안전 장치를 약하게 만든 사본 11개가 기존 시험을 모두 통과했다 — 작업 단위 `permissions` 에 쓰기 권한·액션의 소유자나 저장소 이름·SHA 값 바꾸기·`persist-credentials: true`·
matrix 에 `self-hosted`·작업 단위 `env` 에 `PYTHONPATH`(이상 `ci.yml`), 다른 `run` 단계(내려받기 명령)·한 줄 흐름식 단계로 태그 액션·`pip --extra-index-url`·빌드 명령을 문자열 출력으로 바꾸기·`persist-credentials: true`
(이상 `package.yml`). 기존 시험은 낱말·정규식 검사였고(액션은 '40자리 16진수로 끝나는가' 만 봤다) `package-ocr.yml` 만 단계 열한 개를 글자 그대로 못박았다(`tests/test_package_ocr_workflow.py`).
이 모듈은 같은 방식(`tests/workflow_yaml_support.py` 의 작은 읽개 — 흐름식·앵커·겹친 키 같은 표기는 읽을 수 없다고 거절)을 두 파일에도 적용한다: 최상위·작업·단계 키와 `with`·`env`·`run` 값이 승인된 목록과 **같아야** 하고,
액션은 승인된 `소유자/저장소@커밋` 쌍(아래 `ACTIONS`)뿐이다. 단계를 더하거나 빼거나 명령·`with` 를 바꾸거나 액션의 SHA 를 갱신하려면 이 목록(과 시험)을 같이 고쳐야 하므로 운영자 눈에 띈다 —
`.github/` 의 변경은 어차피 T3(운영자 승인)이고, 이 시험이 그 승인에 '무엇이 바뀌었는가' 를 글자 단위로 남긴다. 이 파일은 `.github/` 를 읽기만 한다(고치지 않는다).
`ci.yml` 의 matrix 줄(`os: [ubuntu-latest, windows-latest]` 같은 한 줄 목록)은 읽개가 거절하는 표기라, **정해진 세 줄(들여쓰기 8칸의 os·python·shard)만** 따옴표 글로 바꿔 읽는다 — 다른 곳의 흐름식은 그대로 거절된다.
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
# 릴리스 워크플로(`release.yml`, 운영자 확인 048 ① — 결정 D-880에서 D-885)만 쓰는 새 액션 하나 — 값은 2026-11-24 에 GitHub API 태그 목록에서 읽은 v4.3.0 이고 운영자가 병합 전에 공식 태그와 대조한다.
# `ci.yml`·`package.yml` 의 단계 목록은 위 `ACTIONS` 만 쓰므로(`_step_problems`) 영향이 없고, 다른 워크플로가 이 액션을 쓰지 못한다는 것은 `tests/test_release_workflow.py` 가 따로 지킨다.
RELEASE_ONLY_ACTIONS = {"actions/download-artifact": "d3f86a106a0bac45b974a628896c90dbdf5c8093"}
APPROVED_REFS = frozenset(f"{name}@{sha}" for name, sha in {**ACTIONS, **RELEASE_ONLY_ACTIONS}.items())
TOP_KEYS = {"name", "on", "permissions", "concurrency", "jobs"}
STEP_KEYS = {"name", "uses", "with", "run", "env"}
MATRIX_LINE = re.compile(r"(?m)^(        (?:os|python|shard)):[ ]+(\[[^\]\n]*\])[ ]*$")
USES = re.compile(r"\buses:\s*([^\s,}#]+)")

CI_STEPS = (
    ("uses", "actions/checkout", {"persist-credentials": "false"}, None),
    ("uses", "actions/setup-python", {"python-version": "${{ matrix.python }}"}, None),
    ("run", "python scripts/ci_shard.py", None, {"PYTHONUTF8": "1", "CI_SHARD": "${{ matrix.shard }}", "CI_SHARD_TOTAL": "3"}),
)
CI = {
    "on": {"push": None, "workflow_dispatch": None},
    "permissions": {"contents": "read"},
    "concurrency": {"group": "ci-${{ github.event_name }}-${{ github.ref }}", "cancel-in-progress": "true"},
    "job": "test",
    "job_keys": {"name", "runs-on", "timeout-minutes", "strategy", "steps"},
    "runs_on": "${{ matrix.os }}",
    "timeout": re.compile(r"4[0-9]|5[0-9]|60"),
    "strategy": {"fail-fast": "false", "matrix": {"os": "[ubuntu-latest, windows-latest]", "python": "['3.10', '3.12']", "shard": "[1, 2, 3]"}},
    "env": None,
    "steps": CI_STEPS,
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
PACKAGE = {
    "on": {"workflow_dispatch": None},
    "permissions": {"contents": "read"},
    "concurrency": {"group": "package-${{ github.ref }}", "cancel-in-progress": "false"},
    "job": "package",
    "job_keys": {"name", "runs-on", "timeout-minutes", "env", "steps"},
    "runs_on": "windows-latest",
    "timeout": re.compile(r"[1-9]|[1-3][0-9]|4[0-5]"),
    "strategy": None,
    "env": {"PYTHONUTF8": "1"},
    "steps": PACKAGE_STEPS,
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
    if not isinstance(jobs, dict) or list(jobs) != [spec["job"]]:
        return problems + [f"작업이 {spec['job']} 하나여야 한다"]
    job = jobs[spec["job"]]
    if not isinstance(job, dict) or set(job) != spec["job_keys"]:
        return problems + [f"작업 키가 정해진 것({sorted(spec['job_keys'])})과 다르다(permissions·env·container·services·defaults·if 같은 키를 못 끼운다): {sorted(job) if isinstance(job, dict) else type(job).__name__}"]
    if job["runs-on"] != spec["runs_on"] or not spec["timeout"].fullmatch(str(job["timeout-minutes"])):
        problems.append(f"runs-on 은 {spec['runs_on']!r}, timeout-minutes 는 정해진 범위여야 한다: {job['runs-on']!r} {job['timeout-minutes']!r}")
    if spec["strategy"] is not None and job.get("strategy") != spec["strategy"]:
        problems.append(f"strategy(matrix)가 승인된 값과 다르다(self-hosted·include·exclude 를 못 끼운다): {job.get('strategy')!r}")
    if spec["env"] is not None and job.get("env") != spec["env"]:
        problems.append(f"작업 env 가 승인된 값과 다르다(PIP_INDEX_URL·PYTHONPATH·프록시 같은 환경 변수를 못 끼운다): {job.get('env')!r}")
    steps = job["steps"]
    expected = spec["steps"]
    if not isinstance(steps, list) or len(steps) != len(expected):
        problems.append(f"단계 목록이 승인된 {len(expected)} 단계와 다르다({len(steps) if isinstance(steps, list) else type(steps).__name__}) — 단계를 더하거나 빼려면 이 허용 목록과 시험을 같이 고친다")
    else:
        for position, (step, wanted) in enumerate(zip(steps, expected), 1):
            problems += _step_problems(position, step, wanted)
    problems += action_problems(text)
    return problems


def ci_problems(text):
    return structure_problems(text, CI)


def package_problems(text):
    return structure_problems(text, PACKAGE)
